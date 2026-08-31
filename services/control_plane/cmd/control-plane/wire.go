package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	apiv1 "github.com/mindclade/mindclade/protocols/generated/go/api/v1"
	annotations "google.golang.org/genproto/googleapis/api/annotations"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/dynamicpb"
)

type trainingFoundation interface {
	CreateTrainingRun(context.Context, *apiv1.CreateTrainingRunRequest) (*apiv1.Operation, error)
	GetTrainingRun(context.Context, *apiv1.GetResourceRequest) (*apiv1.TrainingRunView, error)
	ListTrainingRuns(context.Context, *apiv1.ListResourcesRequest) (*apiv1.TrainingRunList, error)
	GetOperation(context.Context, *apiv1.GetResourceRequest) (*apiv1.Operation, error)
	CancelOperation(context.Context, *apiv1.CancelOperationRequest) (*apiv1.Operation, error)
	WatchOperation(*apiv1.WatchOperationRequest, grpc.ServerStreamingServer[apiv1.OperationEvent]) error
}

// unavailableTrainingFoundation is fail-closed until a durable application
// implementation is injected. It never acknowledges work that cannot survive restart.
type unavailableTrainingFoundation struct{}

func (unavailableTrainingFoundation) unavailable() error {
	return status.Error(codes.Unavailable, "durable foundation training backend is not configured")
}

func (u unavailableTrainingFoundation) CreateTrainingRun(context.Context, *apiv1.CreateTrainingRunRequest) (*apiv1.Operation, error) {
	return nil, u.unavailable()
}
func (u unavailableTrainingFoundation) GetTrainingRun(context.Context, *apiv1.GetResourceRequest) (*apiv1.TrainingRunView, error) {
	return nil, u.unavailable()
}
func (u unavailableTrainingFoundation) ListTrainingRuns(context.Context, *apiv1.ListResourcesRequest) (*apiv1.TrainingRunList, error) {
	return nil, u.unavailable()
}
func (u unavailableTrainingFoundation) GetOperation(context.Context, *apiv1.GetResourceRequest) (*apiv1.Operation, error) {
	return nil, u.unavailable()
}
func (u unavailableTrainingFoundation) CancelOperation(context.Context, *apiv1.CancelOperationRequest) (*apiv1.Operation, error) {
	return nil, u.unavailable()
}
func (u unavailableTrainingFoundation) WatchOperation(*apiv1.WatchOperationRequest, grpc.ServerStreamingServer[apiv1.OperationEvent]) error {
	return u.unavailable()
}

type publicServer struct {
	apiv1.UnimplementedMindcladeServiceServer
	training trainingFoundation
}

func (s *publicServer) CreateTrainingRun(ctx context.Context, request *apiv1.CreateTrainingRunRequest) (*apiv1.Operation, error) {
	if request.GetParent() == "" || request.GetTrainingRun() == nil {
		return nil, status.Error(codes.InvalidArgument, "parent and trainingRun are required")
	}
	return s.training.CreateTrainingRun(ctx, request)
}
func (s *publicServer) GetTrainingRun(ctx context.Context, request *apiv1.GetResourceRequest) (*apiv1.TrainingRunView, error) {
	return s.training.GetTrainingRun(ctx, request)
}
func (s *publicServer) ListTrainingRuns(ctx context.Context, request *apiv1.ListResourcesRequest) (*apiv1.TrainingRunList, error) {
	return s.training.ListTrainingRuns(ctx, request)
}
func (s *publicServer) GetOperation(ctx context.Context, request *apiv1.GetResourceRequest) (*apiv1.Operation, error) {
	return s.training.GetOperation(ctx, request)
}
func (s *publicServer) CancelOperation(ctx context.Context, request *apiv1.CancelOperationRequest) (*apiv1.Operation, error) {
	return s.training.CancelOperation(ctx, request)
}
func (s *publicServer) WatchOperation(request *apiv1.WatchOperationRequest, stream grpc.ServerStreamingServer[apiv1.OperationEvent]) error {
	return s.training.WatchOperation(request, stream)
}

type bearerAuthorizer struct {
	token string
}

func (a bearerAuthorizer) authorize(value string) error {
	if a.token == "" {
		return status.Error(codes.Unavailable, "authentication verifier is not configured")
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(value, prefix) {
		return status.Error(codes.Unauthenticated, "bearer authentication required")
	}
	provided := strings.TrimPrefix(value, prefix)
	if len(provided) != len(a.token) ||
		subtle.ConstantTimeCompare([]byte(provided), []byte(a.token)) != 1 {
		return status.Error(codes.Unauthenticated, "invalid bearer credential")
	}
	return nil
}

func (a bearerAuthorizer) unary(
	ctx context.Context,
	request any,
	info *grpc.UnaryServerInfo,
	handler grpc.UnaryHandler,
) (any, error) {
	values, _ := metadata.FromIncomingContext(ctx)
	if err := a.authorize(first(values.Get("authorization"))); err != nil {
		return nil, err
	}
	return handler(ctx, request)
}

func (a bearerAuthorizer) stream(
	server any,
	stream grpc.ServerStream,
	info *grpc.StreamServerInfo,
	handler grpc.StreamHandler,
) error {
	values, _ := metadata.FromIncomingContext(stream.Context())
	if err := a.authorize(first(values.Get("authorization"))); err != nil {
		return err
	}
	return handler(server, stream)
}

func first(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return values[0]
}

type route struct {
	body       string
	contract   *apiv1.PublicHttpContract
	expression *regexp.Regexp
	httpMethod string
	method     protoreflect.MethodDescriptor
	pathFields []string
}

type gateway struct {
	authorizer bearerAuthorizer
	client     apiv1.MindcladeServiceClient
	conn       *grpc.ClientConn
	routes     []route
}

var pathBinding = regexp.MustCompile(`\{([a-zA-Z][a-zA-Z0-9_]*)=([^{}]+)\}`)

func compilePath(template string) (*regexp.Regexp, []string, error) {
	fields := make([]string, 0)
	var result strings.Builder
	result.WriteString("^")
	cursor := 0
	for _, location := range pathBinding.FindAllStringSubmatchIndex(template, -1) {
		result.WriteString(regexp.QuoteMeta(template[cursor:location[0]]))
		field := template[location[2]:location[3]]
		resourceTemplate := template[location[4]:location[5]]
		fields = append(fields, field)
		parts := strings.Split(resourceTemplate, "*")
		result.WriteString("(?P<")
		result.WriteString(field)
		result.WriteString(">")
		for index, part := range parts {
			result.WriteString(regexp.QuoteMeta(part))
			if index < len(parts)-1 {
				result.WriteString("[^/]+")
			}
		}
		result.WriteString(")")
		cursor = location[1]
	}
	result.WriteString(regexp.QuoteMeta(template[cursor:]))
	result.WriteString("$")
	compiled, err := regexp.Compile(result.String())
	return compiled, fields, err
}

func httpRule(method protoreflect.MethodDescriptor) (string, string, string, error) {
	options := method.Options()
	value := proto.GetExtension(options, annotations.E_Http)
	rule, ok := value.(*annotations.HttpRule)
	if !ok || rule == nil {
		return "", "", "", fmt.Errorf("%s has no google.api.http rule", method.FullName())
	}
	switch {
	case rule.GetGet() != "":
		return http.MethodGet, rule.GetGet(), rule.GetBody(), nil
	case rule.GetPost() != "":
		return http.MethodPost, rule.GetPost(), rule.GetBody(), nil
	case rule.GetPatch() != "":
		return http.MethodPatch, rule.GetPatch(), rule.GetBody(), nil
	case rule.GetPut() != "":
		return http.MethodPut, rule.GetPut(), rule.GetBody(), nil
	case rule.GetDelete() != "":
		return http.MethodDelete, rule.GetDelete(), rule.GetBody(), nil
	default:
		return "", "", "", fmt.Errorf("%s uses an unsupported HTTP rule", method.FullName())
	}
}

func newGateway(conn *grpc.ClientConn, authorizer bearerAuthorizer) (*gateway, error) {
	service := apiv1.File_proto_mindclade_api_v1_mindclade_service_proto.
		Services().ByName("MindcladeService")
	routes := make([]route, 0, service.Methods().Len())
	for index := 0; index < service.Methods().Len(); index++ {
		method := service.Methods().Get(index)
		httpMethod, template, body, err := httpRule(method)
		if err != nil {
			return nil, err
		}
		expression, fields, err := compilePath(template)
		if err != nil {
			return nil, fmt.Errorf("compile route for %s: %w", method.FullName(), err)
		}
		value := proto.GetExtension(method.Options(), apiv1.E_PublicHttp)
		contract, ok := value.(*apiv1.PublicHttpContract)
		if !ok || contract == nil {
			return nil, fmt.Errorf("%s has no public HTTP contract", method.FullName())
		}
		routes = append(routes, route{
			body: body, contract: contract, expression: expression,
			httpMethod: httpMethod, method: method, pathFields: fields,
		})
	}
	return &gateway{
		authorizer: authorizer,
		client:     apiv1.NewMindcladeServiceClient(conn),
		conn:       conn,
		routes:     routes,
	}, nil
}

func (g *gateway) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	if request.Method == http.MethodGet && request.URL.Path == "/healthz" {
		if g.authorizer.token == "" {
			http.Error(writer, "not ready", http.StatusServiceUnavailable)
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"status":"ready"}`))
		return
	}
	for _, candidate := range g.routes {
		if candidate.httpMethod != request.Method {
			continue
		}
		matches := candidate.expression.FindStringSubmatch(request.URL.Path)
		if matches == nil {
			continue
		}
		g.serveRoute(writer, request, candidate, matches)
		return
	}
	writeHTTPError(writer, status.Error(codes.NotFound, "route not found"))
}

func (g *gateway) serveRoute(writer http.ResponseWriter, request *http.Request, selected route, matches []string) {
	if err := g.authorizer.authorize(request.Header.Get("Authorization")); err != nil {
		writeHTTPError(writer, err)
		return
	}
	for _, header := range selected.contract.GetRequestHeaders() {
		if requiredHeader(header) && request.Header.Get(header) == "" {
			writeHTTPError(writer, status.Errorf(codes.InvalidArgument, "%s header is required", header))
			return
		}
	}
	input := dynamicpb.NewMessage(selected.method.Input())
	for _, fieldName := range selected.pathFields {
		index := selected.expression.SubexpIndex(fieldName)
		field := input.Descriptor().Fields().ByName(protoreflect.Name(fieldName))
		if field == nil || index < 0 {
			writeHTTPError(writer, status.Error(codes.Internal, "invalid route binding"))
			return
		}
		input.Set(field, protoreflect.ValueOfString(matches[index]))
	}
	if err := populateQuery(input, request, selected); err != nil {
		writeHTTPError(writer, status.Error(codes.InvalidArgument, err.Error()))
		return
	}
	if selected.body != "" {
		field := input.Descriptor().Fields().ByName(protoreflect.Name(selected.body))
		if field == nil || field.Message() == nil {
			writeHTTPError(writer, status.Error(codes.Internal, "invalid request body binding"))
			return
		}
		payload, err := io.ReadAll(io.LimitReader(request.Body, (4<<20)+1))
		if err != nil {
			writeHTTPError(writer, status.Error(codes.InvalidArgument, "cannot read request body"))
			return
		}
		if len(payload) > 4<<20 {
			writeHTTPError(writer, status.Error(codes.ResourceExhausted, "request body is too large"))
			return
		}
		if err := (protojson.UnmarshalOptions{DiscardUnknown: false}).Unmarshal(
			payload, input.Mutable(field).Message().Interface(),
		); err != nil {
			writeHTTPError(writer, status.Error(codes.InvalidArgument, "invalid ProtoJSON body"))
			return
		}
	}
	ctx := outgoingContext(request)
	switch selected.contract.GetStream() {
	case apiv1.StreamProjection_STREAM_PROJECTION_SSE:
		g.serveSSE(ctx, writer, input)
	case apiv1.StreamProjection_STREAM_PROJECTION_BINARY:
		g.serveBinary(ctx, writer, input, request.Header.Get("Range"))
	default:
		output := dynamicpb.NewMessage(selected.method.Output())
		fullMethod := "/" + string(selected.method.Parent().FullName()) + "/" + string(selected.method.Name())
		if err := g.conn.Invoke(ctx, fullMethod, input, output); err != nil {
			writeHTTPError(writer, err)
			return
		}
		for _, header := range selected.contract.GetResponseHeaders() {
			if strings.EqualFold(header, "ETag") {
				field := output.Descriptor().Fields().ByName("etag")
				if field != nil {
					writer.Header().Set("ETag", output.Get(field).String())
				}
			}
		}
		content, err := protojson.MarshalOptions{UseProtoNames: false}.Marshal(output)
		if err != nil {
			writeHTTPError(writer, status.Error(codes.Internal, "response serialization failed"))
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(successStatus(selected.contract))
		_, _ = writer.Write(content)
	}
}

func populateQuery(message *dynamicpb.Message, request *http.Request, selected route) error {
	bound := make(map[string]bool, len(selected.pathFields)+1)
	for _, name := range selected.pathFields {
		bound[name] = true
	}
	bound[selected.body] = true
	fields := message.Descriptor().Fields()
	allowed := make(map[string]bool, fields.Len())
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		if bound[string(field.Name())] {
			continue
		}
		allowed[field.JSONName()] = true
		raw := request.URL.Query().Get(field.JSONName())
		if raw == "" {
			continue
		}
		switch field.Kind() {
		case protoreflect.StringKind:
			message.Set(field, protoreflect.ValueOfString(raw))
		case protoreflect.Uint32Kind:
			value, err := strconv.ParseUint(raw, 10, 32)
			if err != nil {
				return fmt.Errorf("%s must be uint32", field.JSONName())
			}
			message.Set(field, protoreflect.ValueOfUint32(uint32(value)))
		case protoreflect.Uint64Kind:
			value, err := strconv.ParseUint(raw, 10, 64)
			if err != nil {
				return fmt.Errorf("%s must be uint64", field.JSONName())
			}
			message.Set(field, protoreflect.ValueOfUint64(value))
		default:
			return fmt.Errorf("%s is not a supported query field", field.JSONName())
		}
	}
	for name := range request.URL.Query() {
		if !allowed[name] {
			return fmt.Errorf("unknown query parameter %s", name)
		}
	}
	return nil
}

func outgoingContext(request *http.Request) context.Context {
	pairs := []string{"authorization", request.Header.Get("Authorization")}
	for _, header := range []string{
		"Idempotency-Key", "X-Mindclade-Deadline", "If-Match",
		"If-None-Match", "Last-Event-ID", "Range",
	} {
		if value := request.Header.Get(header); value != "" {
			pairs = append(pairs, strings.ToLower(header), value)
		}
	}
	return metadata.NewOutgoingContext(request.Context(), metadata.Pairs(pairs...))
}

func requiredHeader(name string) bool {
	switch strings.ToLower(name) {
	case "idempotency-key", "x-mindclade-deadline", "if-match":
		return true
	default:
		return false
	}
}

func successStatus(contract *apiv1.PublicHttpContract) int {
	if len(contract.GetSuccessStatus()) == 0 {
		return http.StatusOK
	}
	return int(contract.GetSuccessStatus()[0])
}

func (g *gateway) serveSSE(ctx context.Context, writer http.ResponseWriter, input *dynamicpb.Message) {
	name := input.Get(input.Descriptor().Fields().ByName("name")).String()
	stream, err := g.client.WatchOperation(ctx, &apiv1.WatchOperationRequest{Name: name})
	if err != nil {
		writeHTTPError(writer, err)
		return
	}
	flusher, ok := writer.(http.Flusher)
	if !ok {
		writeHTTPError(writer, status.Error(codes.Unimplemented, "streaming is unavailable"))
		return
	}
	writer.Header().Set("Content-Type", "text/event-stream")
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Accel-Buffering", "no")
	writer.WriteHeader(http.StatusOK)
	for {
		event, receiveErr := stream.Recv()
		if errors.Is(receiveErr, io.EOF) {
			return
		}
		if receiveErr != nil {
			slog.Warn("operation SSE stream ended", "error", receiveErr)
			return
		}
		payload, marshalErr := protojson.Marshal(event)
		if marshalErr != nil {
			slog.Error("operation SSE serialization failed", "error", marshalErr)
			return
		}
		eventID := strings.NewReplacer("\r", "", "\n", "").Replace(event.GetEventId())
		if _, writeErr := fmt.Fprintf(
			writer, "id: %s\nevent: operation\ndata: %s\n\n", eventID, payload,
		); writeErr != nil {
			return
		}
		flusher.Flush()
	}
}

func (g *gateway) serveBinary(ctx context.Context, writer http.ResponseWriter, input *dynamicpb.Message, byteRange string) {
	name := input.Get(input.Descriptor().Fields().ByName("name")).String()
	stream, err := g.client.DownloadArtifact(ctx, &apiv1.DownloadArtifactRequest{Name: name})
	if err != nil {
		writeHTTPError(writer, err)
		return
	}
	firstChunk := true
	for {
		chunk, receiveErr := stream.Recv()
		if errors.Is(receiveErr, io.EOF) {
			return
		}
		if receiveErr != nil {
			slog.Warn("artifact stream ended", "error", receiveErr)
			return
		}
		if firstChunk {
			writer.Header().Set("Content-Type", "application/octet-stream")
			writer.Header().Set("Accept-Ranges", "bytes")
			if chunk.GetContentDigest() != "" {
				writer.Header().Set("Content-Digest", chunk.GetContentDigest())
			}
			if byteRange != "" {
				writer.WriteHeader(http.StatusPartialContent)
			} else {
				writer.WriteHeader(http.StatusOK)
			}
			firstChunk = false
		}
		if _, writeErr := writer.Write(chunk.GetData()); writeErr != nil {
			return
		}
	}
}

func writeHTTPError(writer http.ResponseWriter, err error) {
	grpcStatus := status.Convert(err)
	httpStatus := http.StatusInternalServerError
	publicCode := "INTERNAL"
	publicMessage := "request failed"
	switch grpcStatus.Code() {
	case codes.InvalidArgument:
		httpStatus, publicCode, publicMessage = http.StatusBadRequest, "INVALID_ARGUMENT", "request is invalid"
	case codes.Unauthenticated:
		httpStatus, publicCode, publicMessage = http.StatusUnauthorized, "AUTHENTICATION_REQUIRED", "authentication required"
	case codes.PermissionDenied:
		httpStatus, publicCode, publicMessage = http.StatusForbidden, "PERMISSION_DENIED", "permission denied"
	case codes.NotFound:
		httpStatus, publicCode, publicMessage = http.StatusNotFound, "NOT_FOUND", "resource not found"
	case codes.AlreadyExists, codes.Aborted:
		httpStatus, publicCode, publicMessage = http.StatusConflict, "CONFLICT", "request conflicts with current state"
	case codes.ResourceExhausted:
		httpStatus, publicCode, publicMessage = http.StatusTooManyRequests, "RATE_LIMITED", "request limit exceeded"
	case codes.FailedPrecondition:
		httpStatus, publicCode, publicMessage = http.StatusPreconditionFailed, "FAILED_PRECONDITION", "request precondition failed"
	case codes.Unavailable:
		httpStatus, publicCode, publicMessage = http.StatusServiceUnavailable, "UNAVAILABLE", "service unavailable"
	case codes.DeadlineExceeded:
		httpStatus, publicCode, publicMessage = http.StatusGatewayTimeout, "DEADLINE_EXCEEDED", "request deadline exceeded"
	case codes.Canceled:
		httpStatus, publicCode, publicMessage = 499, "CANCELLED", "request cancelled"
	}
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(httpStatus)
	_ = json.NewEncoder(writer).Encode(map[string]any{
		"code": publicCode, "message": publicMessage, "retryable": grpcStatus.Code() == codes.Unavailable,
		"requestId": fmt.Sprintf("gateway-%d", time.Now().UTC().UnixNano()),
	})
}

type runtime struct {
	grpcListener net.Listener
	grpcServer   *grpc.Server
	httpServer   *http.Server
	conn         *grpc.ClientConn
}

func newRuntime(grpcAddress, httpAddress, token string, training trainingFoundation) (*runtime, error) {
	if err := requireLoopback(grpcAddress); err != nil {
		return nil, fmt.Errorf("gRPC address: %w", err)
	}
	if err := requireLoopback(httpAddress); err != nil {
		return nil, fmt.Errorf("HTTP address: %w", err)
	}
	if training == nil {
		training = unavailableTrainingFoundation{}
	}
	authorizer := bearerAuthorizer{token: token}
	listener, err := net.Listen("tcp", grpcAddress)
	if err != nil {
		return nil, fmt.Errorf("listen for gRPC: %w", err)
	}
	grpcServer := grpc.NewServer(
		grpc.UnaryInterceptor(authorizer.unary),
		grpc.StreamInterceptor(authorizer.stream),
	)
	apiv1.RegisterMindcladeServiceServer(grpcServer, &publicServer{training: training})
	conn, err := grpc.NewClient(
		listener.Addr().String(),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		_ = listener.Close()
		return nil, fmt.Errorf("create loopback gRPC client: %w", err)
	}
	httpGateway, err := newGateway(conn, authorizer)
	if err != nil {
		_ = conn.Close()
		_ = listener.Close()
		return nil, fmt.Errorf("build HTTP gateway: %w", err)
	}
	return &runtime{
		grpcListener: listener,
		grpcServer:   grpcServer,
		httpServer: &http.Server{
			Addr:              httpAddress,
			Handler:           httpGateway,
			ReadHeaderTimeout: 10 * time.Second,
			ReadTimeout:       30 * time.Second,
			WriteTimeout:      0,
			IdleTimeout:       90 * time.Second,
			MaxHeaderBytes:    64 << 10,
		},
		conn: conn,
	}, nil
}

func requireLoopback(address string) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return err
	}
	if strings.EqualFold(host, "localhost") {
		return nil
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return errors.New("must bind to a loopback address; terminate TLS at an authenticated proxy")
	}
	return nil
}

func (r *runtime) serve() error {
	failures := make(chan error, 2)
	go func() { failures <- r.grpcServer.Serve(r.grpcListener) }()
	go func() { failures <- r.httpServer.ListenAndServe() }()
	err := <-failures
	if errors.Is(err, http.ErrServerClosed) || errors.Is(err, grpc.ErrServerStopped) {
		return nil
	}
	return err
}

func (r *runtime) shutdown(ctx context.Context) error {
	httpErr := r.httpServer.Shutdown(ctx)
	r.grpcServer.GracefulStop()
	connErr := r.conn.Close()
	return errors.Join(httpErr, connErr)
}
