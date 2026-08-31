// @generated
/// Generated client implementations.
pub mod artifact_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** ArtifactService owns artifact metadata, aliases, commit, quarantine, and retention RPCs.
*/
    #[derive(Debug, Clone)]
    pub struct ArtifactServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl ArtifactServiceClient<tonic::transport::Channel> {
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
    impl<T> ArtifactServiceClient<T>
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
        ) -> ArtifactServiceClient<InterceptedService<T, F>>
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
            ArtifactServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** GetArtifact reads immutable metadata without returning a provider storage locator.
*/
        pub async fn get_artifact(
            &mut self,
            request: impl tonic::IntoRequest<super::GetArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetArtifactResponse>,
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
                "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.artifact.v1.ArtifactService",
                        "GetArtifact",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListArtifacts returns a bounded, authorization-filtered catalog page.
*/
        pub async fn list_artifacts(
            &mut self,
            request: impl tonic::IntoRequest<super::ListArtifactsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListArtifactsResponse>,
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
                "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.artifact.v1.ArtifactService",
                        "ListArtifacts",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ResolveArtifactAlias resolves a mutable alias at one observed catalog revision.
*/
        pub async fn resolve_artifact_alias(
            &mut self,
            request: impl tonic::IntoRequest<super::ResolveArtifactAliasRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ResolveArtifactAliasResponse>,
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
                "/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.artifact.v1.ArtifactService",
                        "ResolveArtifactAlias",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CommitArtifact atomically verifies and commits staged immutable content.
*/
        pub async fn commit_artifact(
            &mut self,
            request: impl tonic::IntoRequest<super::CommitArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitArtifactResponse>,
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
                "/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.artifact.v1.ArtifactService",
                        "CommitArtifact",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** QuarantineArtifact returns a durable operation for the governed state transition.
*/
        pub async fn quarantine_artifact(
            &mut self,
            request: impl tonic::IntoRequest<super::QuarantineArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<super::QuarantineArtifactResponse>,
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
                "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.artifact.v1.ArtifactService",
                        "QuarantineArtifact",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** AcquireArtifactLease creates or extends bounded retention idempotently.
*/
        pub async fn acquire_artifact_lease(
            &mut self,
            request: impl tonic::IntoRequest<super::AcquireArtifactLeaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::AcquireArtifactLeaseResponse>,
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
                "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.artifact.v1.ArtifactService",
                        "AcquireArtifactLease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ReleaseArtifactLease enforces the supplied ETag and has no response payload.
*/
        pub async fn release_artifact_lease(
            &mut self,
            request: impl tonic::IntoRequest<super::ReleaseArtifactLeaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ReleaseArtifactLeaseResponse>,
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
                "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.artifact.v1.ArtifactService",
                        "ReleaseArtifactLease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod artifact_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with ArtifactServiceServer.
    #[async_trait]
    pub trait ArtifactService: std::marker::Send + std::marker::Sync + 'static {
        /** GetArtifact reads immutable metadata without returning a provider storage locator.
*/
        async fn get_artifact(
            &self,
            request: tonic::Request<super::GetArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetArtifactResponse>,
            tonic::Status,
        >;
        /** ListArtifacts returns a bounded, authorization-filtered catalog page.
*/
        async fn list_artifacts(
            &self,
            request: tonic::Request<super::ListArtifactsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListArtifactsResponse>,
            tonic::Status,
        >;
        /** ResolveArtifactAlias resolves a mutable alias at one observed catalog revision.
*/
        async fn resolve_artifact_alias(
            &self,
            request: tonic::Request<super::ResolveArtifactAliasRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ResolveArtifactAliasResponse>,
            tonic::Status,
        >;
        /** CommitArtifact atomically verifies and commits staged immutable content.
*/
        async fn commit_artifact(
            &self,
            request: tonic::Request<super::CommitArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitArtifactResponse>,
            tonic::Status,
        >;
        /** QuarantineArtifact returns a durable operation for the governed state transition.
*/
        async fn quarantine_artifact(
            &self,
            request: tonic::Request<super::QuarantineArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<super::QuarantineArtifactResponse>,
            tonic::Status,
        >;
        /** AcquireArtifactLease creates or extends bounded retention idempotently.
*/
        async fn acquire_artifact_lease(
            &self,
            request: tonic::Request<super::AcquireArtifactLeaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::AcquireArtifactLeaseResponse>,
            tonic::Status,
        >;
        /** ReleaseArtifactLease enforces the supplied ETag and has no response payload.
*/
        async fn release_artifact_lease(
            &self,
            request: tonic::Request<super::ReleaseArtifactLeaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ReleaseArtifactLeaseResponse>,
            tonic::Status,
        >;
    }
    /** ArtifactService owns artifact metadata, aliases, commit, quarantine, and retention RPCs.
*/
    #[derive(Debug)]
    pub struct ArtifactServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> ArtifactServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for ArtifactServiceServer<T>
    where
        T: ArtifactService,
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
                "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact" => {
                    #[allow(non_camel_case_types)]
                    struct GetArtifactSvc<T: ArtifactService>(pub Arc<T>);
                    impl<
                        T: ArtifactService,
                    > tonic::server::UnaryService<super::GetArtifactRequest>
                    for GetArtifactSvc<T> {
                        type Response = super::GetArtifactResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetArtifactRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ArtifactService>::get_artifact(&inner, request).await
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
                        let method = GetArtifactSvc(inner);
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
                "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts" => {
                    #[allow(non_camel_case_types)]
                    struct ListArtifactsSvc<T: ArtifactService>(pub Arc<T>);
                    impl<
                        T: ArtifactService,
                    > tonic::server::UnaryService<super::ListArtifactsRequest>
                    for ListArtifactsSvc<T> {
                        type Response = super::ListArtifactsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListArtifactsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ArtifactService>::list_artifacts(&inner, request)
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
                        let method = ListArtifactsSvc(inner);
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
                "/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias" => {
                    #[allow(non_camel_case_types)]
                    struct ResolveArtifactAliasSvc<T: ArtifactService>(pub Arc<T>);
                    impl<
                        T: ArtifactService,
                    > tonic::server::UnaryService<super::ResolveArtifactAliasRequest>
                    for ResolveArtifactAliasSvc<T> {
                        type Response = super::ResolveArtifactAliasResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ResolveArtifactAliasRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ArtifactService>::resolve_artifact_alias(
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
                        let method = ResolveArtifactAliasSvc(inner);
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
                "/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact" => {
                    #[allow(non_camel_case_types)]
                    struct CommitArtifactSvc<T: ArtifactService>(pub Arc<T>);
                    impl<
                        T: ArtifactService,
                    > tonic::server::UnaryService<super::CommitArtifactRequest>
                    for CommitArtifactSvc<T> {
                        type Response = super::CommitArtifactResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CommitArtifactRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ArtifactService>::commit_artifact(&inner, request)
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
                        let method = CommitArtifactSvc(inner);
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
                "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact" => {
                    #[allow(non_camel_case_types)]
                    struct QuarantineArtifactSvc<T: ArtifactService>(pub Arc<T>);
                    impl<
                        T: ArtifactService,
                    > tonic::server::UnaryService<super::QuarantineArtifactRequest>
                    for QuarantineArtifactSvc<T> {
                        type Response = super::QuarantineArtifactResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::QuarantineArtifactRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ArtifactService>::quarantine_artifact(&inner, request)
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
                        let method = QuarantineArtifactSvc(inner);
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
                "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease" => {
                    #[allow(non_camel_case_types)]
                    struct AcquireArtifactLeaseSvc<T: ArtifactService>(pub Arc<T>);
                    impl<
                        T: ArtifactService,
                    > tonic::server::UnaryService<super::AcquireArtifactLeaseRequest>
                    for AcquireArtifactLeaseSvc<T> {
                        type Response = super::AcquireArtifactLeaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::AcquireArtifactLeaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ArtifactService>::acquire_artifact_lease(
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
                        let method = AcquireArtifactLeaseSvc(inner);
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
                "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease" => {
                    #[allow(non_camel_case_types)]
                    struct ReleaseArtifactLeaseSvc<T: ArtifactService>(pub Arc<T>);
                    impl<
                        T: ArtifactService,
                    > tonic::server::UnaryService<super::ReleaseArtifactLeaseRequest>
                    for ReleaseArtifactLeaseSvc<T> {
                        type Response = super::ReleaseArtifactLeaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ReleaseArtifactLeaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as ArtifactService>::release_artifact_lease(
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
                        let method = ReleaseArtifactLeaseSvc(inner);
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
    impl<T> Clone for ArtifactServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.artifact.v1.ArtifactService";
    impl<T> tonic::server::NamedService for ArtifactServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
