// @generated
/// Generated client implementations.
pub mod model_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** ModelService owns model registry, release, promotion, and revocation RPCs.
*/
    #[derive(Debug, Clone)]
    pub struct ModelServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl ModelServiceClient<tonic::transport::Channel> {
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
    impl<T> ModelServiceClient<T>
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
        ) -> ModelServiceClient<InterceptedService<T, F>>
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
            ModelServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** RegisterModel performs idempotent model registration.
*/
        pub async fn register_model(
            &mut self,
            request: impl tonic::IntoRequest<super::RegisterModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RegisterModelResponse>,
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
                "/mindclade.internal.model.v1.ModelService/RegisterModel",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "RegisterModel",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetModel reads one model revision.
*/
        pub async fn get_model(
            &mut self,
            request: impl tonic::IntoRequest<super::GetModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetModelResponse>,
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
                "/mindclade.internal.model.v1.ModelService/GetModel",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "GetModel",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListModels returns a bounded project-scoped page.
*/
        pub async fn list_models(
            &mut self,
            request: impl tonic::IntoRequest<super::ListModelsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListModelsResponse>,
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
                "/mindclade.internal.model.v1.ModelService/ListModels",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "ListModels",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** RegisterModelRelease verifies immutable bundles and evidence asynchronously.
*/
        pub async fn register_model_release(
            &mut self,
            request: impl tonic::IntoRequest<super::RegisterModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RegisterModelReleaseResponse>,
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
                "/mindclade.internal.model.v1.ModelService/RegisterModelRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "RegisterModelRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetModelRelease reads one model release.
*/
        pub async fn get_model_release(
            &mut self,
            request: impl tonic::IntoRequest<super::GetModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetModelReleaseResponse>,
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
                "/mindclade.internal.model.v1.ModelService/GetModelRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "GetModelRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListModelReleases lists releases under one model.
*/
        pub async fn list_model_releases(
            &mut self,
            request: impl tonic::IntoRequest<super::ListModelReleasesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListModelReleasesResponse>,
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
                "/mindclade.internal.model.v1.ModelService/ListModelReleases",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "ListModelReleases",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** PromoteModelRelease enforces the current ETag, stage, policy, and evidence.
*/
        pub async fn promote_model_release(
            &mut self,
            request: impl tonic::IntoRequest<super::PromoteModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::PromoteModelReleaseResponse>,
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
                "/mindclade.internal.model.v1.ModelService/PromoteModelRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "PromoteModelRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** RevokeModelRelease records a new audited disposition without rewriting history.
*/
        pub async fn revoke_model_release(
            &mut self,
            request: impl tonic::IntoRequest<super::RevokeModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RevokeModelReleaseResponse>,
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
                "/mindclade.internal.model.v1.ModelService/RevokeModelRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.model.v1.ModelService",
                        "RevokeModelRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod model_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with ModelServiceServer.
    #[async_trait]
    pub trait ModelService: std::marker::Send + std::marker::Sync + 'static {
        /** RegisterModel performs idempotent model registration.
*/
        async fn register_model(
            &self,
            request: tonic::Request<super::RegisterModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RegisterModelResponse>,
            tonic::Status,
        >;
        /** GetModel reads one model revision.
*/
        async fn get_model(
            &self,
            request: tonic::Request<super::GetModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetModelResponse>,
            tonic::Status,
        >;
        /** ListModels returns a bounded project-scoped page.
*/
        async fn list_models(
            &self,
            request: tonic::Request<super::ListModelsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListModelsResponse>,
            tonic::Status,
        >;
        /** RegisterModelRelease verifies immutable bundles and evidence asynchronously.
*/
        async fn register_model_release(
            &self,
            request: tonic::Request<super::RegisterModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RegisterModelReleaseResponse>,
            tonic::Status,
        >;
        /** GetModelRelease reads one model release.
*/
        async fn get_model_release(
            &self,
            request: tonic::Request<super::GetModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetModelReleaseResponse>,
            tonic::Status,
        >;
        /** ListModelReleases lists releases under one model.
*/
        async fn list_model_releases(
            &self,
            request: tonic::Request<super::ListModelReleasesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListModelReleasesResponse>,
            tonic::Status,
        >;
        /** PromoteModelRelease enforces the current ETag, stage, policy, and evidence.
*/
        async fn promote_model_release(
            &self,
            request: tonic::Request<super::PromoteModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::PromoteModelReleaseResponse>,
            tonic::Status,
        >;
        /** RevokeModelRelease records a new audited disposition without rewriting history.
*/
        async fn revoke_model_release(
            &self,
            request: tonic::Request<super::RevokeModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RevokeModelReleaseResponse>,
            tonic::Status,
        >;
    }
    /** ModelService owns model registry, release, promotion, and revocation RPCs.
*/
    #[derive(Debug)]
    pub struct ModelServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> ModelServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for ModelServiceServer<T>
    where
        T: ModelService,
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
                "/mindclade.internal.model.v1.ModelService/RegisterModel" => {
                    #[allow(non_camel_case_types)]
                    struct RegisterModelSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::RegisterModelRequest>
                    for RegisterModelSvc<T> {
                        type Response = super::RegisterModelResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::RegisterModelRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::register_model(&inner, request).await
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
                        let method = RegisterModelSvc(inner);
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
                "/mindclade.internal.model.v1.ModelService/GetModel" => {
                    #[allow(non_camel_case_types)]
                    struct GetModelSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::GetModelRequest>
                    for GetModelSvc<T> {
                        type Response = super::GetModelResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetModelRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::get_model(&inner, request).await
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
                        let method = GetModelSvc(inner);
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
                "/mindclade.internal.model.v1.ModelService/ListModels" => {
                    #[allow(non_camel_case_types)]
                    struct ListModelsSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::ListModelsRequest>
                    for ListModelsSvc<T> {
                        type Response = super::ListModelsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListModelsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::list_models(&inner, request).await
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
                        let method = ListModelsSvc(inner);
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
                "/mindclade.internal.model.v1.ModelService/RegisterModelRelease" => {
                    #[allow(non_camel_case_types)]
                    struct RegisterModelReleaseSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::RegisterModelReleaseRequest>
                    for RegisterModelReleaseSvc<T> {
                        type Response = super::RegisterModelReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::RegisterModelReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::register_model_release(&inner, request)
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
                        let method = RegisterModelReleaseSvc(inner);
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
                "/mindclade.internal.model.v1.ModelService/GetModelRelease" => {
                    #[allow(non_camel_case_types)]
                    struct GetModelReleaseSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::GetModelReleaseRequest>
                    for GetModelReleaseSvc<T> {
                        type Response = super::GetModelReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetModelReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::get_model_release(&inner, request)
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
                        let method = GetModelReleaseSvc(inner);
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
                "/mindclade.internal.model.v1.ModelService/ListModelReleases" => {
                    #[allow(non_camel_case_types)]
                    struct ListModelReleasesSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::ListModelReleasesRequest>
                    for ListModelReleasesSvc<T> {
                        type Response = super::ListModelReleasesResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListModelReleasesRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::list_model_releases(&inner, request)
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
                        let method = ListModelReleasesSvc(inner);
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
                "/mindclade.internal.model.v1.ModelService/PromoteModelRelease" => {
                    #[allow(non_camel_case_types)]
                    struct PromoteModelReleaseSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::PromoteModelReleaseRequest>
                    for PromoteModelReleaseSvc<T> {
                        type Response = super::PromoteModelReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::PromoteModelReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::promote_model_release(&inner, request)
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
                        let method = PromoteModelReleaseSvc(inner);
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
                "/mindclade.internal.model.v1.ModelService/RevokeModelRelease" => {
                    #[allow(non_camel_case_types)]
                    struct RevokeModelReleaseSvc<T: ModelService>(pub Arc<T>);
                    impl<
                        T: ModelService,
                    > tonic::server::UnaryService<super::RevokeModelReleaseRequest>
                    for RevokeModelReleaseSvc<T> {
                        type Response = super::RevokeModelReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::RevokeModelReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ModelService>::revoke_model_release(&inner, request)
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
                        let method = RevokeModelReleaseSvc(inner);
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
    impl<T> Clone for ModelServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.model.v1.ModelService";
    impl<T> tonic::server::NamedService for ModelServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
