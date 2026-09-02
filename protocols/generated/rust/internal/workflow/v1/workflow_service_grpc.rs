// @generated
/// Generated client implementations.
pub mod workflow_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** WorkflowService owns graph definitions, durable runs, and fenced transitions.
*/
    #[derive(Debug, Clone)]
    pub struct WorkflowServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl WorkflowServiceClient<tonic::transport::Channel> {
        /// Attempt to create a new client by connecting to a given endpoint.
        pub async fn connect<D>(dst: D) -> Result<Self, tonic::transport::Error>
        where
            D: TryInto<tonic::transport::Endpoint>,
            D::Error: Into<StdError>,
        {
            let conn = tonic::transport::Endpoint::new(dst)?.connect().await?;
            Ok(Self::new(conn))
        }
    }
    impl<T> WorkflowServiceClient<T>
    where
        T: tonic::client::GrpcService<tonic::body::Body>,
        T::Error: Into<StdError>,
        T::ResponseBody: Body<Data = Bytes> + std::marker::Send + 'static,
        <T::ResponseBody as Body>::Error: Into<StdError> + std::marker::Send,
    {
        pub fn new(inner: T) -> Self {
            let inner = tonic::client::Grpc::new(inner);
            Self { inner }
        }
        pub fn with_origin(inner: T, origin: Uri) -> Self {
            let inner = tonic::client::Grpc::with_origin(inner, origin);
            Self { inner }
        }
        pub fn with_interceptor<F>(
            inner: T,
            interceptor: F,
        ) -> WorkflowServiceClient<InterceptedService<T, F>>
        where
            F: tonic::service::Interceptor,
            T::ResponseBody: Default,
            T: tonic::codegen::Service<
                http::Request<tonic::body::Body>,
                Response = http::Response<
                    <T as tonic::client::GrpcService<tonic::body::Body>>::ResponseBody,
                >,
            >,
            <T as tonic::codegen::Service<
                http::Request<tonic::body::Body>,
            >>::Error: Into<StdError> + std::marker::Send + std::marker::Sync,
        {
            WorkflowServiceClient::new(InterceptedService::new(inner, interceptor))
        }
        /// Compress requests with the given encoding.
        /// This requires the server to support it otherwise it might respond with an
        /// error.
        #[must_use]
        pub fn send_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.inner = self.inner.send_compressed(encoding);
            self
        }
        /// Enable decompressing responses.
        #[must_use]
        pub fn accept_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.inner = self.inner.accept_compressed(encoding);
            self
        }
        /// Limits the maximum size of a decoded message.
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_decoding_message_size(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_encoding_message_size(limit);
            self
        }
        /** CreateWorkflowDefinition validates the referenced graph before persistence.
*/
        pub async fn create_workflow_definition(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateWorkflowDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateWorkflowDefinitionResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "CreateWorkflowDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** UpdateWorkflowDefinition applies only masked metadata under optimistic concurrency.
*/
        pub async fn update_workflow_definition(
            &mut self,
            request: impl tonic::IntoRequest<super::UpdateWorkflowDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateWorkflowDefinitionResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "UpdateWorkflowDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetWorkflowDefinition reads one definition revision.
*/
        pub async fn get_workflow_definition(
            &mut self,
            request: impl tonic::IntoRequest<super::GetWorkflowDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetWorkflowDefinitionResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "GetWorkflowDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListWorkflowDefinitions returns a bounded project-scoped page.
*/
        pub async fn list_workflow_definitions(
            &mut self,
            request: impl tonic::IntoRequest<super::ListWorkflowDefinitionsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListWorkflowDefinitionsResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "ListWorkflowDefinitions",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** StartWorkflowRun freezes execution intent and returns durable asynchronous state.
*/
        pub async fn start_workflow_run(
            &mut self,
            request: impl tonic::IntoRequest<super::StartWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::StartWorkflowRunResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "StartWorkflowRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetWorkflowRun reads one durable run.
*/
        pub async fn get_workflow_run(
            &mut self,
            request: impl tonic::IntoRequest<super::GetWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetWorkflowRunResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "GetWorkflowRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListWorkflowRuns returns a bounded authorization-filtered page.
*/
        pub async fn list_workflow_runs(
            &mut self,
            request: impl tonic::IntoRequest<super::ListWorkflowRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListWorkflowRunsResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "ListWorkflowRuns",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CancelWorkflowRun records monotonic cancellation.
*/
        pub async fn cancel_workflow_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CancelWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelWorkflowRunResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "CancelWorkflowRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CommitWorkflowTransition rejects stale sequences and lease epochs.
*/
        pub async fn commit_workflow_transition(
            &mut self,
            request: impl tonic::IntoRequest<super::CommitWorkflowTransitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitWorkflowTransitionResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "CommitWorkflowTransition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** WatchWorkflowRun streams ordered revisions from a durable resume cursor.
*/
        pub async fn watch_workflow_run(
            &mut self,
            request: impl tonic::IntoRequest<super::WatchWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<tonic::codec::Streaming<super::WatchWorkflowRunResponse>>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.WorkflowService",
                        "WatchWorkflowRun",
                    ),
                );
            self.inner.server_streaming(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod workflow_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with WorkflowServiceServer.
    #[async_trait]
    pub trait WorkflowService: std::marker::Send + std::marker::Sync + 'static {
        /** CreateWorkflowDefinition validates the referenced graph before persistence.
*/
        async fn create_workflow_definition(
            &self,
            request: tonic::Request<super::CreateWorkflowDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateWorkflowDefinitionResponse>,
            tonic::Status,
        >;
        /** UpdateWorkflowDefinition applies only masked metadata under optimistic concurrency.
*/
        async fn update_workflow_definition(
            &self,
            request: tonic::Request<super::UpdateWorkflowDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateWorkflowDefinitionResponse>,
            tonic::Status,
        >;
        /** GetWorkflowDefinition reads one definition revision.
*/
        async fn get_workflow_definition(
            &self,
            request: tonic::Request<super::GetWorkflowDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetWorkflowDefinitionResponse>,
            tonic::Status,
        >;
        /** ListWorkflowDefinitions returns a bounded project-scoped page.
*/
        async fn list_workflow_definitions(
            &self,
            request: tonic::Request<super::ListWorkflowDefinitionsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListWorkflowDefinitionsResponse>,
            tonic::Status,
        >;
        /** StartWorkflowRun freezes execution intent and returns durable asynchronous state.
*/
        async fn start_workflow_run(
            &self,
            request: tonic::Request<super::StartWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::StartWorkflowRunResponse>,
            tonic::Status,
        >;
        /** GetWorkflowRun reads one durable run.
*/
        async fn get_workflow_run(
            &self,
            request: tonic::Request<super::GetWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetWorkflowRunResponse>,
            tonic::Status,
        >;
        /** ListWorkflowRuns returns a bounded authorization-filtered page.
*/
        async fn list_workflow_runs(
            &self,
            request: tonic::Request<super::ListWorkflowRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListWorkflowRunsResponse>,
            tonic::Status,
        >;
        /** CancelWorkflowRun records monotonic cancellation.
*/
        async fn cancel_workflow_run(
            &self,
            request: tonic::Request<super::CancelWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelWorkflowRunResponse>,
            tonic::Status,
        >;
        /** CommitWorkflowTransition rejects stale sequences and lease epochs.
*/
        async fn commit_workflow_transition(
            &self,
            request: tonic::Request<super::CommitWorkflowTransitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitWorkflowTransitionResponse>,
            tonic::Status,
        >;
        /// Server streaming response type for the WatchWorkflowRun method.
        type WatchWorkflowRunStream: tonic::codegen::tokio_stream::Stream<
                Item = std::result::Result<
                    super::WatchWorkflowRunResponse,
                    tonic::Status,
                >,
            >
            + std::marker::Send
            + 'static;
        /** WatchWorkflowRun streams ordered revisions from a durable resume cursor.
*/
        async fn watch_workflow_run(
            &self,
            request: tonic::Request<super::WatchWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<Self::WatchWorkflowRunStream>,
            tonic::Status,
        >;
    }
    /** WorkflowService owns graph definitions, durable runs, and fenced transitions.
*/
    #[derive(Debug)]
    pub struct WorkflowServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> WorkflowServiceServer<T> {
        pub fn new(inner: T) -> Self {
            Self::from_arc(Arc::new(inner))
        }
        pub fn from_arc(inner: Arc<T>) -> Self {
            Self {
                inner,
                accept_compression_encodings: Default::default(),
                send_compression_encodings: Default::default(),
                max_decoding_message_size: None,
                max_encoding_message_size: None,
            }
        }
        pub fn with_interceptor<F>(
            inner: T,
            interceptor: F,
        ) -> InterceptedService<Self, F>
        where
            F: tonic::service::Interceptor,
        {
            InterceptedService::new(Self::new(inner), interceptor)
        }
        /// Enable decompressing requests with the given encoding.
        #[must_use]
        pub fn accept_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.accept_compression_encodings.enable(encoding);
            self
        }
        /// Compress responses with the given encoding, if the client supports it.
        #[must_use]
        pub fn send_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.send_compression_encodings.enable(encoding);
            self
        }
        /// Limits the maximum size of a decoded message.
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.max_decoding_message_size = Some(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.max_encoding_message_size = Some(limit);
            self
        }
    }
    impl<T, B> tonic::codegen::Service<http::Request<B>> for WorkflowServiceServer<T>
    where
        T: WorkflowService,
        B: Body + std::marker::Send + 'static,
        B::Error: Into<StdError> + std::marker::Send + 'static,
    {
        type Response = http::Response<tonic::body::Body>;
        type Error = std::convert::Infallible;
        type Future = BoxFuture<Self::Response, Self::Error>;
        fn poll_ready(
            &mut self,
            _cx: &mut Context<'_>,
        ) -> Poll<std::result::Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }
        fn call(&mut self, req: http::Request<B>) -> Self::Future {
            match req.uri().path() {
                "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct CreateWorkflowDefinitionSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::CreateWorkflowDefinitionRequest>
                    for CreateWorkflowDefinitionSvc<T> {
                        type Response = super::CreateWorkflowDefinitionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<
                                super::CreateWorkflowDefinitionRequest,
                            >,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::create_workflow_definition(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = CreateWorkflowDefinitionSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct UpdateWorkflowDefinitionSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::UpdateWorkflowDefinitionRequest>
                    for UpdateWorkflowDefinitionSvc<T> {
                        type Response = super::UpdateWorkflowDefinitionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<
                                super::UpdateWorkflowDefinitionRequest,
                            >,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::update_workflow_definition(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = UpdateWorkflowDefinitionSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct GetWorkflowDefinitionSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::GetWorkflowDefinitionRequest>
                    for GetWorkflowDefinitionSvc<T> {
                        type Response = super::GetWorkflowDefinitionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetWorkflowDefinitionRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::get_workflow_definition(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = GetWorkflowDefinitionSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions" => {
                    #[allow(non_camel_case_types)]
                    struct ListWorkflowDefinitionsSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::ListWorkflowDefinitionsRequest>
                    for ListWorkflowDefinitionsSvc<T> {
                        type Response = super::ListWorkflowDefinitionsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<
                                super::ListWorkflowDefinitionsRequest,
                            >,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::list_workflow_definitions(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = ListWorkflowDefinitionsSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun" => {
                    #[allow(non_camel_case_types)]
                    struct StartWorkflowRunSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::StartWorkflowRunRequest>
                    for StartWorkflowRunSvc<T> {
                        type Response = super::StartWorkflowRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::StartWorkflowRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::start_workflow_run(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = StartWorkflowRunSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetWorkflowRunSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::GetWorkflowRunRequest>
                    for GetWorkflowRunSvc<T> {
                        type Response = super::GetWorkflowRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetWorkflowRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::get_workflow_run(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = GetWorkflowRunSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListWorkflowRunsSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::ListWorkflowRunsRequest>
                    for ListWorkflowRunsSvc<T> {
                        type Response = super::ListWorkflowRunsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListWorkflowRunsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::list_workflow_runs(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = ListWorkflowRunsSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun" => {
                    #[allow(non_camel_case_types)]
                    struct CancelWorkflowRunSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::CancelWorkflowRunRequest>
                    for CancelWorkflowRunSvc<T> {
                        type Response = super::CancelWorkflowRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CancelWorkflowRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::cancel_workflow_run(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = CancelWorkflowRunSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition" => {
                    #[allow(non_camel_case_types)]
                    struct CommitWorkflowTransitionSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::UnaryService<super::CommitWorkflowTransitionRequest>
                    for CommitWorkflowTransitionSvc<T> {
                        type Response = super::CommitWorkflowTransitionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<
                                super::CommitWorkflowTransitionRequest,
                            >,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::commit_workflow_transition(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = CommitWorkflowTransitionSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun" => {
                    #[allow(non_camel_case_types)]
                    struct WatchWorkflowRunSvc<T: WorkflowService>(pub Arc<T>);
                    impl<
                        T: WorkflowService,
                    > tonic::server::ServerStreamingService<
                        super::WatchWorkflowRunRequest,
                    > for WatchWorkflowRunSvc<T> {
                        type Response = super::WatchWorkflowRunResponse;
                        type ResponseStream = T::WatchWorkflowRunStream;
                        type Future = BoxFuture<
                            tonic::Response<Self::ResponseStream>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::WatchWorkflowRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as WorkflowService>::watch_workflow_run(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = WatchWorkflowRunSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.server_streaming(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                _ => {
                    Box::pin(async move {
                        let mut response = http::Response::new(
                            tonic::body::Body::default(),
                        );
                        let headers = response.headers_mut();
                        headers
                            .insert(
                                tonic::Status::GRPC_STATUS,
                                (tonic::Code::Unimplemented as i32).into(),
                            );
                        headers
                            .insert(
                                http::header::CONTENT_TYPE,
                                tonic::metadata::GRPC_CONTENT_TYPE,
                            );
                        Ok(response)
                    })
                }
            }
        }
    }
    impl<T> Clone for WorkflowServiceServer<T> {
        fn clone(&self) -> Self {
            let inner = self.inner.clone();
            Self {
                inner,
                accept_compression_encodings: self.accept_compression_encodings,
                send_compression_encodings: self.send_compression_encodings,
                max_decoding_message_size: self.max_decoding_message_size,
                max_encoding_message_size: self.max_encoding_message_size,
            }
        }
    }
    /// Generated gRPC service name
    pub const SERVICE_NAME: &str = "mindclade.internal.workflow.v1.WorkflowService";
    impl<T> tonic::server::NamedService for WorkflowServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
/// Generated client implementations.
pub mod approval_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** ApprovalService owns exact-intent human approval and single-use consumption.
*/
    #[derive(Debug, Clone)]
    pub struct ApprovalServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl ApprovalServiceClient<tonic::transport::Channel> {
        /// Attempt to create a new client by connecting to a given endpoint.
        pub async fn connect<D>(dst: D) -> Result<Self, tonic::transport::Error>
        where
            D: TryInto<tonic::transport::Endpoint>,
            D::Error: Into<StdError>,
        {
            let conn = tonic::transport::Endpoint::new(dst)?.connect().await?;
            Ok(Self::new(conn))
        }
    }
    impl<T> ApprovalServiceClient<T>
    where
        T: tonic::client::GrpcService<tonic::body::Body>,
        T::Error: Into<StdError>,
        T::ResponseBody: Body<Data = Bytes> + std::marker::Send + 'static,
        <T::ResponseBody as Body>::Error: Into<StdError> + std::marker::Send,
    {
        pub fn new(inner: T) -> Self {
            let inner = tonic::client::Grpc::new(inner);
            Self { inner }
        }
        pub fn with_origin(inner: T, origin: Uri) -> Self {
            let inner = tonic::client::Grpc::with_origin(inner, origin);
            Self { inner }
        }
        pub fn with_interceptor<F>(
            inner: T,
            interceptor: F,
        ) -> ApprovalServiceClient<InterceptedService<T, F>>
        where
            F: tonic::service::Interceptor,
            T::ResponseBody: Default,
            T: tonic::codegen::Service<
                http::Request<tonic::body::Body>,
                Response = http::Response<
                    <T as tonic::client::GrpcService<tonic::body::Body>>::ResponseBody,
                >,
            >,
            <T as tonic::codegen::Service<
                http::Request<tonic::body::Body>,
            >>::Error: Into<StdError> + std::marker::Send + std::marker::Sync,
        {
            ApprovalServiceClient::new(InterceptedService::new(inner, interceptor))
        }
        /// Compress requests with the given encoding.
        /// This requires the server to support it otherwise it might respond with an
        /// error.
        #[must_use]
        pub fn send_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.inner = self.inner.send_compressed(encoding);
            self
        }
        /// Enable decompressing responses.
        #[must_use]
        pub fn accept_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.inner = self.inner.accept_compressed(encoding);
            self
        }
        /// Limits the maximum size of a decoded message.
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_decoding_message_size(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_encoding_message_size(limit);
            self
        }
        /** RequestApproval persists the exact consequential action shown to approvers.
*/
        pub async fn request_approval(
            &mut self,
            request: impl tonic::IntoRequest<super::RequestApprovalRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RequestApprovalResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.ApprovalService",
                        "RequestApproval",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetApprovalRequest reads one durable request.
*/
        pub async fn get_approval_request(
            &mut self,
            request: impl tonic::IntoRequest<super::GetApprovalRequestRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetApprovalRequestResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.ApprovalService",
                        "GetApprovalRequest",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListApprovalRequests returns a bounded authorization-filtered page.
*/
        pub async fn list_approval_requests(
            &mut self,
            request: impl tonic::IntoRequest<super::ListApprovalRequestsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListApprovalRequestsResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.ApprovalService",
                        "ListApprovalRequests",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** DecideApproval creates immutable evidence from an authenticated human decision.
*/
        pub async fn decide_approval(
            &mut self,
            request: impl tonic::IntoRequest<super::DecideApprovalRequest>,
        ) -> std::result::Result<
            tonic::Response<super::DecideApprovalResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.ApprovalService",
                        "DecideApproval",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ConsumeApproval atomically enforces binding, expiry, and reuse semantics.
*/
        pub async fn consume_approval(
            &mut self,
            request: impl tonic::IntoRequest<super::ConsumeApprovalRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ConsumeApprovalResponse>,
            tonic::Status,
        > {
            self.inner
                .ready()
                .await
                .map_err(|e| {
                    tonic::Status::unknown(
                        format!("Service was not ready: {}", e.into()),
                    )
                })?;
            let codec = tonic_prost::ProstCodec::default();
            let path = http::uri::PathAndQuery::from_static(
                "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.workflow.v1.ApprovalService",
                        "ConsumeApproval",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod approval_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with ApprovalServiceServer.
    #[async_trait]
    pub trait ApprovalService: std::marker::Send + std::marker::Sync + 'static {
        /** RequestApproval persists the exact consequential action shown to approvers.
*/
        async fn request_approval(
            &self,
            request: tonic::Request<super::RequestApprovalRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RequestApprovalResponse>,
            tonic::Status,
        >;
        /** GetApprovalRequest reads one durable request.
*/
        async fn get_approval_request(
            &self,
            request: tonic::Request<super::GetApprovalRequestRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetApprovalRequestResponse>,
            tonic::Status,
        >;
        /** ListApprovalRequests returns a bounded authorization-filtered page.
*/
        async fn list_approval_requests(
            &self,
            request: tonic::Request<super::ListApprovalRequestsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListApprovalRequestsResponse>,
            tonic::Status,
        >;
        /** DecideApproval creates immutable evidence from an authenticated human decision.
*/
        async fn decide_approval(
            &self,
            request: tonic::Request<super::DecideApprovalRequest>,
        ) -> std::result::Result<
            tonic::Response<super::DecideApprovalResponse>,
            tonic::Status,
        >;
        /** ConsumeApproval atomically enforces binding, expiry, and reuse semantics.
*/
        async fn consume_approval(
            &self,
            request: tonic::Request<super::ConsumeApprovalRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ConsumeApprovalResponse>,
            tonic::Status,
        >;
    }
    /** ApprovalService owns exact-intent human approval and single-use consumption.
*/
    #[derive(Debug)]
    pub struct ApprovalServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> ApprovalServiceServer<T> {
        pub fn new(inner: T) -> Self {
            Self::from_arc(Arc::new(inner))
        }
        pub fn from_arc(inner: Arc<T>) -> Self {
            Self {
                inner,
                accept_compression_encodings: Default::default(),
                send_compression_encodings: Default::default(),
                max_decoding_message_size: None,
                max_encoding_message_size: None,
            }
        }
        pub fn with_interceptor<F>(
            inner: T,
            interceptor: F,
        ) -> InterceptedService<Self, F>
        where
            F: tonic::service::Interceptor,
        {
            InterceptedService::new(Self::new(inner), interceptor)
        }
        /// Enable decompressing requests with the given encoding.
        #[must_use]
        pub fn accept_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.accept_compression_encodings.enable(encoding);
            self
        }
        /// Compress responses with the given encoding, if the client supports it.
        #[must_use]
        pub fn send_compressed(mut self, encoding: CompressionEncoding) -> Self {
            self.send_compression_encodings.enable(encoding);
            self
        }
        /// Limits the maximum size of a decoded message.
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.max_decoding_message_size = Some(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.max_encoding_message_size = Some(limit);
            self
        }
    }
    impl<T, B> tonic::codegen::Service<http::Request<B>> for ApprovalServiceServer<T>
    where
        T: ApprovalService,
        B: Body + std::marker::Send + 'static,
        B::Error: Into<StdError> + std::marker::Send + 'static,
    {
        type Response = http::Response<tonic::body::Body>;
        type Error = std::convert::Infallible;
        type Future = BoxFuture<Self::Response, Self::Error>;
        fn poll_ready(
            &mut self,
            _cx: &mut Context<'_>,
        ) -> Poll<std::result::Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }
        fn call(&mut self, req: http::Request<B>) -> Self::Future {
            match req.uri().path() {
                "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval" => {
                    #[allow(non_camel_case_types)]
                    struct RequestApprovalSvc<T: ApprovalService>(pub Arc<T>);
                    impl<
                        T: ApprovalService,
                    > tonic::server::UnaryService<super::RequestApprovalRequest>
                    for RequestApprovalSvc<T> {
                        type Response = super::RequestApprovalResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::RequestApprovalRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ApprovalService>::request_approval(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = RequestApprovalSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest" => {
                    #[allow(non_camel_case_types)]
                    struct GetApprovalRequestSvc<T: ApprovalService>(pub Arc<T>);
                    impl<
                        T: ApprovalService,
                    > tonic::server::UnaryService<super::GetApprovalRequestRequest>
                    for GetApprovalRequestSvc<T> {
                        type Response = super::GetApprovalRequestResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetApprovalRequestRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ApprovalService>::get_approval_request(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = GetApprovalRequestSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests" => {
                    #[allow(non_camel_case_types)]
                    struct ListApprovalRequestsSvc<T: ApprovalService>(pub Arc<T>);
                    impl<
                        T: ApprovalService,
                    > tonic::server::UnaryService<super::ListApprovalRequestsRequest>
                    for ListApprovalRequestsSvc<T> {
                        type Response = super::ListApprovalRequestsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListApprovalRequestsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ApprovalService>::list_approval_requests(
                                        &inner,
                                        request,
                                    )
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = ListApprovalRequestsSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval" => {
                    #[allow(non_camel_case_types)]
                    struct DecideApprovalSvc<T: ApprovalService>(pub Arc<T>);
                    impl<
                        T: ApprovalService,
                    > tonic::server::UnaryService<super::DecideApprovalRequest>
                    for DecideApprovalSvc<T> {
                        type Response = super::DecideApprovalResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::DecideApprovalRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ApprovalService>::decide_approval(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = DecideApprovalSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval" => {
                    #[allow(non_camel_case_types)]
                    struct ConsumeApprovalSvc<T: ApprovalService>(pub Arc<T>);
                    impl<
                        T: ApprovalService,
                    > tonic::server::UnaryService<super::ConsumeApprovalRequest>
                    for ConsumeApprovalSvc<T> {
                        type Response = super::ConsumeApprovalResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ConsumeApprovalRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ApprovalService>::consume_approval(&inner, request)
                                    .await
                            };
                            Box::pin(fut)
                        }
                    }
                    let accept_compression_encodings = self.accept_compression_encodings;
                    let send_compression_encodings = self.send_compression_encodings;
                    let max_decoding_message_size = self.max_decoding_message_size;
                    let max_encoding_message_size = self.max_encoding_message_size;
                    let inner = self.inner.clone();
                    let fut = async move {
                        let method = ConsumeApprovalSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec)
                            .apply_compression_config(
                                accept_compression_encodings,
                                send_compression_encodings,
                            )
                            .apply_max_message_size_config(
                                max_decoding_message_size,
                                max_encoding_message_size,
                            );
                        let res = grpc.unary(method, req).await;
                        Ok(res)
                    };
                    Box::pin(fut)
                }
                _ => {
                    Box::pin(async move {
                        let mut response = http::Response::new(
                            tonic::body::Body::default(),
                        );
                        let headers = response.headers_mut();
                        headers
                            .insert(
                                tonic::Status::GRPC_STATUS,
                                (tonic::Code::Unimplemented as i32).into(),
                            );
                        headers
                            .insert(
                                http::header::CONTENT_TYPE,
                                tonic::metadata::GRPC_CONTENT_TYPE,
                            );
                        Ok(response)
                    })
                }
            }
        }
    }
    impl<T> Clone for ApprovalServiceServer<T> {
        fn clone(&self) -> Self {
            let inner = self.inner.clone();
            Self {
                inner,
                accept_compression_encodings: self.accept_compression_encodings,
                send_compression_encodings: self.send_compression_encodings,
                max_decoding_message_size: self.max_decoding_message_size,
                max_encoding_message_size: self.max_encoding_message_size,
            }
        }
    }
    /// Generated gRPC service name
    pub const SERVICE_NAME: &str = "mindclade.internal.workflow.v1.ApprovalService";
    impl<T> tonic::server::NamedService for ApprovalServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
