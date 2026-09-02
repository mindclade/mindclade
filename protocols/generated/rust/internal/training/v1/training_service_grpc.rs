// @generated
/// Generated client implementations.
pub mod training_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** TrainingService owns training-run, progress, attempt, and checkpoint application RPCs.
*/
    #[derive(Debug, Clone)]
    pub struct TrainingServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl TrainingServiceClient<tonic::transport::Channel> {
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
    impl<T> TrainingServiceClient<T>
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
        ) -> TrainingServiceClient<InterceptedService<T, F>>
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
            TrainingServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** CreateTrainingRun returns a durable operation for validation and admission.
*/
        pub async fn create_training_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateTrainingRunResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "CreateTrainingRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetTrainingRun reads one scientific run.
*/
        pub async fn get_training_run(
            &mut self,
            request: impl tonic::IntoRequest<super::GetTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetTrainingRunResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/GetTrainingRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "GetTrainingRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListTrainingRuns returns a bounded authorization-filtered page.
*/
        pub async fn list_training_runs(
            &mut self,
            request: impl tonic::IntoRequest<super::ListTrainingRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListTrainingRunsResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/ListTrainingRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "ListTrainingRuns",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** StartTrainingAttempt rejects stale or mismatched fences.
*/
        pub async fn start_training_attempt(
            &mut self,
            request: impl tonic::IntoRequest<super::StartTrainingAttemptRequest>,
        ) -> std::result::Result<
            tonic::Response<super::StartTrainingAttemptResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "StartTrainingAttempt",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ResumeTrainingAttempt binds recovery to an immutable checkpoint.
*/
        pub async fn resume_training_attempt(
            &mut self,
            request: impl tonic::IntoRequest<super::ResumeTrainingAttemptRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ResumeTrainingAttemptResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "ResumeTrainingAttempt",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CommitTrainingProgress accepts only monotonic progress from the current fence.
*/
        pub async fn commit_training_progress(
            &mut self,
            request: impl tonic::IntoRequest<super::CommitTrainingProgressRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitTrainingProgressResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "CommitTrainingProgress",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** PrepareCheckpoint establishes the atomic snapshot boundary.
*/
        pub async fn prepare_checkpoint(
            &mut self,
            request: impl tonic::IntoRequest<super::PrepareCheckpointRequest>,
        ) -> std::result::Result<
            tonic::Response<super::PrepareCheckpointResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "PrepareCheckpoint",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CommitCheckpoint verifies immutable artifacts before publication.
*/
        pub async fn commit_checkpoint(
            &mut self,
            request: impl tonic::IntoRequest<super::CommitCheckpointRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitCheckpointResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/CommitCheckpoint",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "CommitCheckpoint",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CompleteTrainingRun accepts one fenced terminal outcome.
*/
        pub async fn complete_training_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CompleteTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CompleteTrainingRunResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "CompleteTrainingRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CancelTrainingRun records monotonic desired cancellation under an ETag.
*/
        pub async fn cancel_training_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CancelTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelTrainingRunResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/CancelTrainingRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "CancelTrainingRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetCheckpoint reads one checkpoint.
*/
        pub async fn get_checkpoint(
            &mut self,
            request: impl tonic::IntoRequest<super::GetCheckpointRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetCheckpointResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/GetCheckpoint",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "GetCheckpoint",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListCheckpoints lists checkpoints for a training run.
*/
        pub async fn list_checkpoints(
            &mut self,
            request: impl tonic::IntoRequest<super::ListCheckpointsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListCheckpointsResponse>,
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
                "/mindclade.internal.training.v1.TrainingService/ListCheckpoints",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "ListCheckpoints",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** WatchTrainingRun streams resumable revisions; the durable run remains authoritative.
*/
        pub async fn watch_training_run(
            &mut self,
            request: impl tonic::IntoRequest<super::WatchTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<tonic::codec::Streaming<super::WatchTrainingRunResponse>>,
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
                "/mindclade.internal.training.v1.TrainingService/WatchTrainingRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.training.v1.TrainingService",
                        "WatchTrainingRun",
                    ),
                );
            self.inner.server_streaming(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod training_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with TrainingServiceServer.
    #[async_trait]
    pub trait TrainingService: std::marker::Send + std::marker::Sync + 'static {
        /** CreateTrainingRun returns a durable operation for validation and admission.
*/
        async fn create_training_run(
            &self,
            request: tonic::Request<super::CreateTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateTrainingRunResponse>,
            tonic::Status,
        >;
        /** GetTrainingRun reads one scientific run.
*/
        async fn get_training_run(
            &self,
            request: tonic::Request<super::GetTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetTrainingRunResponse>,
            tonic::Status,
        >;
        /** ListTrainingRuns returns a bounded authorization-filtered page.
*/
        async fn list_training_runs(
            &self,
            request: tonic::Request<super::ListTrainingRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListTrainingRunsResponse>,
            tonic::Status,
        >;
        /** StartTrainingAttempt rejects stale or mismatched fences.
*/
        async fn start_training_attempt(
            &self,
            request: tonic::Request<super::StartTrainingAttemptRequest>,
        ) -> std::result::Result<
            tonic::Response<super::StartTrainingAttemptResponse>,
            tonic::Status,
        >;
        /** ResumeTrainingAttempt binds recovery to an immutable checkpoint.
*/
        async fn resume_training_attempt(
            &self,
            request: tonic::Request<super::ResumeTrainingAttemptRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ResumeTrainingAttemptResponse>,
            tonic::Status,
        >;
        /** CommitTrainingProgress accepts only monotonic progress from the current fence.
*/
        async fn commit_training_progress(
            &self,
            request: tonic::Request<super::CommitTrainingProgressRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitTrainingProgressResponse>,
            tonic::Status,
        >;
        /** PrepareCheckpoint establishes the atomic snapshot boundary.
*/
        async fn prepare_checkpoint(
            &self,
            request: tonic::Request<super::PrepareCheckpointRequest>,
        ) -> std::result::Result<
            tonic::Response<super::PrepareCheckpointResponse>,
            tonic::Status,
        >;
        /** CommitCheckpoint verifies immutable artifacts before publication.
*/
        async fn commit_checkpoint(
            &self,
            request: tonic::Request<super::CommitCheckpointRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitCheckpointResponse>,
            tonic::Status,
        >;
        /** CompleteTrainingRun accepts one fenced terminal outcome.
*/
        async fn complete_training_run(
            &self,
            request: tonic::Request<super::CompleteTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CompleteTrainingRunResponse>,
            tonic::Status,
        >;
        /** CancelTrainingRun records monotonic desired cancellation under an ETag.
*/
        async fn cancel_training_run(
            &self,
            request: tonic::Request<super::CancelTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelTrainingRunResponse>,
            tonic::Status,
        >;
        /** GetCheckpoint reads one checkpoint.
*/
        async fn get_checkpoint(
            &self,
            request: tonic::Request<super::GetCheckpointRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetCheckpointResponse>,
            tonic::Status,
        >;
        /** ListCheckpoints lists checkpoints for a training run.
*/
        async fn list_checkpoints(
            &self,
            request: tonic::Request<super::ListCheckpointsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListCheckpointsResponse>,
            tonic::Status,
        >;
        /// Server streaming response type for the WatchTrainingRun method.
        type WatchTrainingRunStream: tonic::codegen::tokio_stream::Stream<
                Item = std::result::Result<
                    super::WatchTrainingRunResponse,
                    tonic::Status,
                >,
            >
            + std::marker::Send
            + 'static;
        /** WatchTrainingRun streams resumable revisions; the durable run remains authoritative.
*/
        async fn watch_training_run(
            &self,
            request: tonic::Request<super::WatchTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<Self::WatchTrainingRunStream>,
            tonic::Status,
        >;
    }
    /** TrainingService owns training-run, progress, attempt, and checkpoint application RPCs.
*/
    #[derive(Debug)]
    pub struct TrainingServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> TrainingServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for TrainingServiceServer<T>
    where
        T: TrainingService,
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
                "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun" => {
                    #[allow(non_camel_case_types)]
                    struct CreateTrainingRunSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::CreateTrainingRunRequest>
                    for CreateTrainingRunSvc<T> {
                        type Response = super::CreateTrainingRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateTrainingRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::create_training_run(&inner, request)
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
                        let method = CreateTrainingRunSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/GetTrainingRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetTrainingRunSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::GetTrainingRunRequest>
                    for GetTrainingRunSvc<T> {
                        type Response = super::GetTrainingRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetTrainingRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::get_training_run(&inner, request)
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
                        let method = GetTrainingRunSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/ListTrainingRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListTrainingRunsSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::ListTrainingRunsRequest>
                    for ListTrainingRunsSvc<T> {
                        type Response = super::ListTrainingRunsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListTrainingRunsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::list_training_runs(&inner, request)
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
                        let method = ListTrainingRunsSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt" => {
                    #[allow(non_camel_case_types)]
                    struct StartTrainingAttemptSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::StartTrainingAttemptRequest>
                    for StartTrainingAttemptSvc<T> {
                        type Response = super::StartTrainingAttemptResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::StartTrainingAttemptRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::start_training_attempt(
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
                        let method = StartTrainingAttemptSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt" => {
                    #[allow(non_camel_case_types)]
                    struct ResumeTrainingAttemptSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::ResumeTrainingAttemptRequest>
                    for ResumeTrainingAttemptSvc<T> {
                        type Response = super::ResumeTrainingAttemptResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ResumeTrainingAttemptRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::resume_training_attempt(
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
                        let method = ResumeTrainingAttemptSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress" => {
                    #[allow(non_camel_case_types)]
                    struct CommitTrainingProgressSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::CommitTrainingProgressRequest>
                    for CommitTrainingProgressSvc<T> {
                        type Response = super::CommitTrainingProgressResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CommitTrainingProgressRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::commit_training_progress(
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
                        let method = CommitTrainingProgressSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint" => {
                    #[allow(non_camel_case_types)]
                    struct PrepareCheckpointSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::PrepareCheckpointRequest>
                    for PrepareCheckpointSvc<T> {
                        type Response = super::PrepareCheckpointResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::PrepareCheckpointRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::prepare_checkpoint(&inner, request)
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
                        let method = PrepareCheckpointSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/CommitCheckpoint" => {
                    #[allow(non_camel_case_types)]
                    struct CommitCheckpointSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::CommitCheckpointRequest>
                    for CommitCheckpointSvc<T> {
                        type Response = super::CommitCheckpointResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CommitCheckpointRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::commit_checkpoint(&inner, request)
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
                        let method = CommitCheckpointSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun" => {
                    #[allow(non_camel_case_types)]
                    struct CompleteTrainingRunSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::CompleteTrainingRunRequest>
                    for CompleteTrainingRunSvc<T> {
                        type Response = super::CompleteTrainingRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CompleteTrainingRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::complete_training_run(
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
                        let method = CompleteTrainingRunSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/CancelTrainingRun" => {
                    #[allow(non_camel_case_types)]
                    struct CancelTrainingRunSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::CancelTrainingRunRequest>
                    for CancelTrainingRunSvc<T> {
                        type Response = super::CancelTrainingRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CancelTrainingRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::cancel_training_run(&inner, request)
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
                        let method = CancelTrainingRunSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/GetCheckpoint" => {
                    #[allow(non_camel_case_types)]
                    struct GetCheckpointSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::GetCheckpointRequest>
                    for GetCheckpointSvc<T> {
                        type Response = super::GetCheckpointResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetCheckpointRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::get_checkpoint(&inner, request)
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
                        let method = GetCheckpointSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/ListCheckpoints" => {
                    #[allow(non_camel_case_types)]
                    struct ListCheckpointsSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::UnaryService<super::ListCheckpointsRequest>
                    for ListCheckpointsSvc<T> {
                        type Response = super::ListCheckpointsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListCheckpointsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::list_checkpoints(&inner, request)
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
                        let method = ListCheckpointsSvc(inner);
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
                "/mindclade.internal.training.v1.TrainingService/WatchTrainingRun" => {
                    #[allow(non_camel_case_types)]
                    struct WatchTrainingRunSvc<T: TrainingService>(pub Arc<T>);
                    impl<
                        T: TrainingService,
                    > tonic::server::ServerStreamingService<
                        super::WatchTrainingRunRequest,
                    > for WatchTrainingRunSvc<T> {
                        type Response = super::WatchTrainingRunResponse;
                        type ResponseStream = T::WatchTrainingRunStream;
                        type Future = BoxFuture<
                            tonic::Response<Self::ResponseStream>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::WatchTrainingRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as TrainingService>::watch_training_run(&inner, request)
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
                        let method = WatchTrainingRunSvc(inner);
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
    impl<T> Clone for TrainingServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.training.v1.TrainingService";
    impl<T> tonic::server::NamedService for TrainingServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
