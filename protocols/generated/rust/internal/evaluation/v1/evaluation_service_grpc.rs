// @generated
/// Generated client implementations.
pub mod evaluation_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** EvaluationService owns evaluation execution, result commit, and promotion evidence RPCs.
*/
    #[derive(Debug, Clone)]
    pub struct EvaluationServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl EvaluationServiceClient<tonic::transport::Channel> {
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
    impl<T> EvaluationServiceClient<T>
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
        ) -> EvaluationServiceClient<InterceptedService<T, F>>
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
            EvaluationServiceClient::new(InterceptedService::new(inner, interceptor))
        }
        /// Compress requests with the given encoding.
        ///
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
        ///
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_decoding_message_size(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        ///
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.inner = self.inner.max_encoding_message_size(limit);
            self
        }
        /** CreateEvaluationRun validates immutable inputs and returns durable asynchronous state.
*/
        pub async fn create_evaluation_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateEvaluationRunResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "CreateEvaluationRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetEvaluationRun reads one durable evaluation run.
*/
        pub async fn get_evaluation_run(
            &mut self,
            request: impl tonic::IntoRequest<super::GetEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetEvaluationRunResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "GetEvaluationRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListEvaluationRuns returns a bounded authorization-filtered page.
*/
        pub async fn list_evaluation_runs(
            &mut self,
            request: impl tonic::IntoRequest<super::ListEvaluationRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListEvaluationRunsResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "ListEvaluationRuns",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CancelEvaluationRun records desired cancellation under optimistic concurrency.
*/
        pub async fn cancel_evaluation_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CancelEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelEvaluationRunResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "CancelEvaluationRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CommitEvaluationResult rejects stale attempts and verifies immutable evidence.
*/
        pub async fn commit_evaluation_result(
            &mut self,
            request: impl tonic::IntoRequest<super::CommitEvaluationResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitEvaluationResultResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "CommitEvaluationResult",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetEvaluationResult reads one immutable result.
*/
        pub async fn get_evaluation_result(
            &mut self,
            request: impl tonic::IntoRequest<super::GetEvaluationResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetEvaluationResultResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "GetEvaluationResult",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreatePromotionDecision records policy and evaluation evidence without deploying anything.
*/
        pub async fn create_promotion_decision(
            &mut self,
            request: impl tonic::IntoRequest<super::CreatePromotionDecisionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreatePromotionDecisionResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "CreatePromotionDecision",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetPromotionDecision reads one immutable governed decision.
*/
        pub async fn get_promotion_decision(
            &mut self,
            request: impl tonic::IntoRequest<super::GetPromotionDecisionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetPromotionDecisionResponse>,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.evaluation.v1.EvaluationService",
                        "GetPromotionDecision",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod evaluation_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with EvaluationServiceServer.
    #[async_trait]
    pub trait EvaluationService: std::marker::Send + std::marker::Sync + 'static {
        /** CreateEvaluationRun validates immutable inputs and returns durable asynchronous state.
*/
        async fn create_evaluation_run(
            &self,
            request: tonic::Request<super::CreateEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateEvaluationRunResponse>,
            tonic::Status,
        >;
        /** GetEvaluationRun reads one durable evaluation run.
*/
        async fn get_evaluation_run(
            &self,
            request: tonic::Request<super::GetEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetEvaluationRunResponse>,
            tonic::Status,
        >;
        /** ListEvaluationRuns returns a bounded authorization-filtered page.
*/
        async fn list_evaluation_runs(
            &self,
            request: tonic::Request<super::ListEvaluationRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListEvaluationRunsResponse>,
            tonic::Status,
        >;
        /** CancelEvaluationRun records desired cancellation under optimistic concurrency.
*/
        async fn cancel_evaluation_run(
            &self,
            request: tonic::Request<super::CancelEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelEvaluationRunResponse>,
            tonic::Status,
        >;
        /** CommitEvaluationResult rejects stale attempts and verifies immutable evidence.
*/
        async fn commit_evaluation_result(
            &self,
            request: tonic::Request<super::CommitEvaluationResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitEvaluationResultResponse>,
            tonic::Status,
        >;
        /** GetEvaluationResult reads one immutable result.
*/
        async fn get_evaluation_result(
            &self,
            request: tonic::Request<super::GetEvaluationResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetEvaluationResultResponse>,
            tonic::Status,
        >;
        /** CreatePromotionDecision records policy and evaluation evidence without deploying anything.
*/
        async fn create_promotion_decision(
            &self,
            request: tonic::Request<super::CreatePromotionDecisionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreatePromotionDecisionResponse>,
            tonic::Status,
        >;
        /** GetPromotionDecision reads one immutable governed decision.
*/
        async fn get_promotion_decision(
            &self,
            request: tonic::Request<super::GetPromotionDecisionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetPromotionDecisionResponse>,
            tonic::Status,
        >;
    }
    /** EvaluationService owns evaluation execution, result commit, and promotion evidence RPCs.
*/
    #[derive(Debug)]
    pub struct EvaluationServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> EvaluationServiceServer<T> {
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
        ///
        /// Default: `4MB`
        #[must_use]
        pub fn max_decoding_message_size(mut self, limit: usize) -> Self {
            self.max_decoding_message_size = Some(limit);
            self
        }
        /// Limits the maximum size of an encoded message.
        ///
        /// Default: `usize::MAX`
        #[must_use]
        pub fn max_encoding_message_size(mut self, limit: usize) -> Self {
            self.max_encoding_message_size = Some(limit);
            self
        }
    }
    impl<T, B> tonic::codegen::Service<http::Request<B>> for EvaluationServiceServer<T>
    where
        T: EvaluationService,
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun" => {
                    #[allow(non_camel_case_types)]
                    struct CreateEvaluationRunSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::CreateEvaluationRunRequest>
                    for CreateEvaluationRunSvc<T> {
                        type Response = super::CreateEvaluationRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateEvaluationRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::create_evaluation_run(
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
                        let method = CreateEvaluationRunSvc(inner);
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
                "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetEvaluationRunSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::GetEvaluationRunRequest>
                    for GetEvaluationRunSvc<T> {
                        type Response = super::GetEvaluationRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetEvaluationRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::get_evaluation_run(
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
                        let method = GetEvaluationRunSvc(inner);
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
                "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListEvaluationRunsSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::ListEvaluationRunsRequest>
                    for ListEvaluationRunsSvc<T> {
                        type Response = super::ListEvaluationRunsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListEvaluationRunsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::list_evaluation_runs(
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
                        let method = ListEvaluationRunsSvc(inner);
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun" => {
                    #[allow(non_camel_case_types)]
                    struct CancelEvaluationRunSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::CancelEvaluationRunRequest>
                    for CancelEvaluationRunSvc<T> {
                        type Response = super::CancelEvaluationRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CancelEvaluationRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::cancel_evaluation_run(
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
                        let method = CancelEvaluationRunSvc(inner);
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult" => {
                    #[allow(non_camel_case_types)]
                    struct CommitEvaluationResultSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::CommitEvaluationResultRequest>
                    for CommitEvaluationResultSvc<T> {
                        type Response = super::CommitEvaluationResultResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CommitEvaluationResultRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::commit_evaluation_result(
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
                        let method = CommitEvaluationResultSvc(inner);
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
                "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult" => {
                    #[allow(non_camel_case_types)]
                    struct GetEvaluationResultSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::GetEvaluationResultRequest>
                    for GetEvaluationResultSvc<T> {
                        type Response = super::GetEvaluationResultResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetEvaluationResultRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::get_evaluation_result(
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
                        let method = GetEvaluationResultSvc(inner);
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
                "/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision" => {
                    #[allow(non_camel_case_types)]
                    struct CreatePromotionDecisionSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::CreatePromotionDecisionRequest>
                    for CreatePromotionDecisionSvc<T> {
                        type Response = super::CreatePromotionDecisionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<
                                super::CreatePromotionDecisionRequest,
                            >,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::create_promotion_decision(
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
                        let method = CreatePromotionDecisionSvc(inner);
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
                "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision" => {
                    #[allow(non_camel_case_types)]
                    struct GetPromotionDecisionSvc<T: EvaluationService>(pub Arc<T>);
                    impl<
                        T: EvaluationService,
                    > tonic::server::UnaryService<super::GetPromotionDecisionRequest>
                    for GetPromotionDecisionSvc<T> {
                        type Response = super::GetPromotionDecisionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetPromotionDecisionRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as EvaluationService>::get_promotion_decision(
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
                        let method = GetPromotionDecisionSvc(inner);
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
    impl<T> Clone for EvaluationServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.evaluation.v1.EvaluationService";
    impl<T> tonic::server::NamedService for EvaluationServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
