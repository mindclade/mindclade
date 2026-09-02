// @generated
/// Generated client implementations.
pub mod experiment_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** ExperimentService owns experiment intent, bounded studies, and immutable trial outcomes.
*/
    #[derive(Debug, Clone)]
    pub struct ExperimentServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl ExperimentServiceClient<tonic::transport::Channel> {
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
    impl<T> ExperimentServiceClient<T>
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
        ) -> ExperimentServiceClient<InterceptedService<T, F>>
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
            ExperimentServiceClient::new(InterceptedService::new(inner, interceptor))
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
        pub async fn create_experiment(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateExperimentResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "CreateExperiment",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn get_experiment(
            &mut self,
            request: impl tonic::IntoRequest<super::GetExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetExperimentResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "GetExperiment",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn list_experiments(
            &mut self,
            request: impl tonic::IntoRequest<super::ListExperimentsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListExperimentsResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "ListExperiments",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn update_experiment(
            &mut self,
            request: impl tonic::IntoRequest<super::UpdateExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateExperimentResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "UpdateExperiment",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn transition_experiment(
            &mut self,
            request: impl tonic::IntoRequest<super::TransitionExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::TransitionExperimentResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "TransitionExperiment",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn create_study(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateStudyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateStudyResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "CreateStudy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn get_study(
            &mut self,
            request: impl tonic::IntoRequest<super::GetStudyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetStudyResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/GetStudy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "GetStudy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn list_studies(
            &mut self,
            request: impl tonic::IntoRequest<super::ListStudiesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListStudiesResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/ListStudies",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "ListStudies",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn transition_study(
            &mut self,
            request: impl tonic::IntoRequest<super::TransitionStudyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::TransitionStudyResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "TransitionStudy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn create_trial(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateTrialResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "CreateTrial",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn get_trial(
            &mut self,
            request: impl tonic::IntoRequest<super::GetTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetTrialResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/GetTrial",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "GetTrial",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn list_trials(
            &mut self,
            request: impl tonic::IntoRequest<super::ListTrialsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListTrialsResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/ListTrials",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "ListTrials",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn transition_trial(
            &mut self,
            request: impl tonic::IntoRequest<super::TransitionTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::TransitionTrialResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "TransitionTrial",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        pub async fn complete_trial(
            &mut self,
            request: impl tonic::IntoRequest<super::CompleteTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CompleteTrialResponse>,
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
                "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.experiment.v1.ExperimentService",
                        "CompleteTrial",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod experiment_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with ExperimentServiceServer.
    #[async_trait]
    pub trait ExperimentService: std::marker::Send + std::marker::Sync + 'static {
        async fn create_experiment(
            &self,
            request: tonic::Request<super::CreateExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateExperimentResponse>,
            tonic::Status,
        >;
        async fn get_experiment(
            &self,
            request: tonic::Request<super::GetExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetExperimentResponse>,
            tonic::Status,
        >;
        async fn list_experiments(
            &self,
            request: tonic::Request<super::ListExperimentsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListExperimentsResponse>,
            tonic::Status,
        >;
        async fn update_experiment(
            &self,
            request: tonic::Request<super::UpdateExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateExperimentResponse>,
            tonic::Status,
        >;
        async fn transition_experiment(
            &self,
            request: tonic::Request<super::TransitionExperimentRequest>,
        ) -> std::result::Result<
            tonic::Response<super::TransitionExperimentResponse>,
            tonic::Status,
        >;
        async fn create_study(
            &self,
            request: tonic::Request<super::CreateStudyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateStudyResponse>,
            tonic::Status,
        >;
        async fn get_study(
            &self,
            request: tonic::Request<super::GetStudyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetStudyResponse>,
            tonic::Status,
        >;
        async fn list_studies(
            &self,
            request: tonic::Request<super::ListStudiesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListStudiesResponse>,
            tonic::Status,
        >;
        async fn transition_study(
            &self,
            request: tonic::Request<super::TransitionStudyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::TransitionStudyResponse>,
            tonic::Status,
        >;
        async fn create_trial(
            &self,
            request: tonic::Request<super::CreateTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateTrialResponse>,
            tonic::Status,
        >;
        async fn get_trial(
            &self,
            request: tonic::Request<super::GetTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetTrialResponse>,
            tonic::Status,
        >;
        async fn list_trials(
            &self,
            request: tonic::Request<super::ListTrialsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListTrialsResponse>,
            tonic::Status,
        >;
        async fn transition_trial(
            &self,
            request: tonic::Request<super::TransitionTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::TransitionTrialResponse>,
            tonic::Status,
        >;
        async fn complete_trial(
            &self,
            request: tonic::Request<super::CompleteTrialRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CompleteTrialResponse>,
            tonic::Status,
        >;
    }
    /** ExperimentService owns experiment intent, bounded studies, and immutable trial outcomes.
*/
    #[derive(Debug)]
    pub struct ExperimentServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> ExperimentServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for ExperimentServiceServer<T>
    where
        T: ExperimentService,
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
                "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment" => {
                    #[allow(non_camel_case_types)]
                    struct CreateExperimentSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::CreateExperimentRequest>
                    for CreateExperimentSvc<T> {
                        type Response = super::CreateExperimentResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateExperimentRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::create_experiment(&inner, request)
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
                        let method = CreateExperimentSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment" => {
                    #[allow(non_camel_case_types)]
                    struct GetExperimentSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::GetExperimentRequest>
                    for GetExperimentSvc<T> {
                        type Response = super::GetExperimentResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetExperimentRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::get_experiment(&inner, request)
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
                        let method = GetExperimentSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments" => {
                    #[allow(non_camel_case_types)]
                    struct ListExperimentsSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::ListExperimentsRequest>
                    for ListExperimentsSvc<T> {
                        type Response = super::ListExperimentsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListExperimentsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::list_experiments(&inner, request)
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
                        let method = ListExperimentsSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment" => {
                    #[allow(non_camel_case_types)]
                    struct UpdateExperimentSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::UpdateExperimentRequest>
                    for UpdateExperimentSvc<T> {
                        type Response = super::UpdateExperimentResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::UpdateExperimentRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::update_experiment(&inner, request)
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
                        let method = UpdateExperimentSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment" => {
                    #[allow(non_camel_case_types)]
                    struct TransitionExperimentSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::TransitionExperimentRequest>
                    for TransitionExperimentSvc<T> {
                        type Response = super::TransitionExperimentResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::TransitionExperimentRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::transition_experiment(
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
                        let method = TransitionExperimentSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy" => {
                    #[allow(non_camel_case_types)]
                    struct CreateStudySvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::CreateStudyRequest>
                    for CreateStudySvc<T> {
                        type Response = super::CreateStudyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateStudyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::create_study(&inner, request)
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
                        let method = CreateStudySvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/GetStudy" => {
                    #[allow(non_camel_case_types)]
                    struct GetStudySvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::GetStudyRequest>
                    for GetStudySvc<T> {
                        type Response = super::GetStudyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetStudyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::get_study(&inner, request).await
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
                        let method = GetStudySvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/ListStudies" => {
                    #[allow(non_camel_case_types)]
                    struct ListStudiesSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::ListStudiesRequest>
                    for ListStudiesSvc<T> {
                        type Response = super::ListStudiesResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListStudiesRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::list_studies(&inner, request)
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
                        let method = ListStudiesSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy" => {
                    #[allow(non_camel_case_types)]
                    struct TransitionStudySvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::TransitionStudyRequest>
                    for TransitionStudySvc<T> {
                        type Response = super::TransitionStudyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::TransitionStudyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::transition_study(&inner, request)
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
                        let method = TransitionStudySvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial" => {
                    #[allow(non_camel_case_types)]
                    struct CreateTrialSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::CreateTrialRequest>
                    for CreateTrialSvc<T> {
                        type Response = super::CreateTrialResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateTrialRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::create_trial(&inner, request)
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
                        let method = CreateTrialSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/GetTrial" => {
                    #[allow(non_camel_case_types)]
                    struct GetTrialSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::GetTrialRequest>
                    for GetTrialSvc<T> {
                        type Response = super::GetTrialResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetTrialRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::get_trial(&inner, request).await
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
                        let method = GetTrialSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/ListTrials" => {
                    #[allow(non_camel_case_types)]
                    struct ListTrialsSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::ListTrialsRequest>
                    for ListTrialsSvc<T> {
                        type Response = super::ListTrialsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListTrialsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::list_trials(&inner, request).await
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
                        let method = ListTrialsSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial" => {
                    #[allow(non_camel_case_types)]
                    struct TransitionTrialSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::TransitionTrialRequest>
                    for TransitionTrialSvc<T> {
                        type Response = super::TransitionTrialResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::TransitionTrialRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::transition_trial(&inner, request)
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
                        let method = TransitionTrialSvc(inner);
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
                "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial" => {
                    #[allow(non_camel_case_types)]
                    struct CompleteTrialSvc<T: ExperimentService>(pub Arc<T>);
                    impl<
                        T: ExperimentService,
                    > tonic::server::UnaryService<super::CompleteTrialRequest>
                    for CompleteTrialSvc<T> {
                        type Response = super::CompleteTrialResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CompleteTrialRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ExperimentService>::complete_trial(&inner, request)
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
                        let method = CompleteTrialSvc(inner);
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
    impl<T> Clone for ExperimentServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.experiment.v1.ExperimentService";
    impl<T> tonic::server::NamedService for ExperimentServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
