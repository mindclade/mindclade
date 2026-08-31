// @generated
/// Generated client implementations.
pub mod dataset_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** DatasetService owns dataset and immutable release application RPCs.
*/
    #[derive(Debug, Clone)]
    pub struct DatasetServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl DatasetServiceClient<tonic::transport::Channel> {
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
    impl<T> DatasetServiceClient<T>
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
        ) -> DatasetServiceClient<InterceptedService<T, F>>
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
            DatasetServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** CreateDataset performs idempotent creation and returns a durable operation.
*/
        pub async fn create_dataset(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateDatasetResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/CreateDataset",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "CreateDataset",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetDataset reads one dataset revision.
*/
        pub async fn get_dataset(
            &mut self,
            request: impl tonic::IntoRequest<super::GetDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetDatasetResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/GetDataset",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "GetDataset",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListDatasets returns a bounded project-scoped page.
*/
        pub async fn list_datasets(
            &mut self,
            request: impl tonic::IntoRequest<super::ListDatasetsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListDatasetsResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/ListDatasets",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "ListDatasets",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** UpdateDataset enforces the command's field mask and ETag.
*/
        pub async fn update_dataset(
            &mut self,
            request: impl tonic::IntoRequest<super::UpdateDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateDatasetResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "UpdateDataset",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** PublishDatasetRelease verifies immutable manifest and policy references asynchronously.
*/
        pub async fn publish_dataset_release(
            &mut self,
            request: impl tonic::IntoRequest<super::PublishDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::PublishDatasetReleaseResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "PublishDatasetRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** RevokeDatasetRelease records evidence without rewriting immutable history.
*/
        pub async fn revoke_dataset_release(
            &mut self,
            request: impl tonic::IntoRequest<super::RevokeDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RevokeDatasetReleaseResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "RevokeDatasetRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetDatasetRelease reads one release.
*/
        pub async fn get_dataset_release(
            &mut self,
            request: impl tonic::IntoRequest<super::GetDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetDatasetReleaseResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "GetDatasetRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListDatasetReleases lists immutable releases under one dataset.
*/
        pub async fn list_dataset_releases(
            &mut self,
            request: impl tonic::IntoRequest<super::ListDatasetReleasesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListDatasetReleasesResponse>,
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
                "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.dataset.v1.DatasetService",
                        "ListDatasetReleases",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod dataset_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with DatasetServiceServer.
    #[async_trait]
    pub trait DatasetService: std::marker::Send + std::marker::Sync + 'static {
        /** CreateDataset performs idempotent creation and returns a durable operation.
*/
        async fn create_dataset(
            &self,
            request: tonic::Request<super::CreateDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateDatasetResponse>,
            tonic::Status,
        >;
        /** GetDataset reads one dataset revision.
*/
        async fn get_dataset(
            &self,
            request: tonic::Request<super::GetDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetDatasetResponse>,
            tonic::Status,
        >;
        /** ListDatasets returns a bounded project-scoped page.
*/
        async fn list_datasets(
            &self,
            request: tonic::Request<super::ListDatasetsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListDatasetsResponse>,
            tonic::Status,
        >;
        /** UpdateDataset enforces the command's field mask and ETag.
*/
        async fn update_dataset(
            &self,
            request: tonic::Request<super::UpdateDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateDatasetResponse>,
            tonic::Status,
        >;
        /** PublishDatasetRelease verifies immutable manifest and policy references asynchronously.
*/
        async fn publish_dataset_release(
            &self,
            request: tonic::Request<super::PublishDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::PublishDatasetReleaseResponse>,
            tonic::Status,
        >;
        /** RevokeDatasetRelease records evidence without rewriting immutable history.
*/
        async fn revoke_dataset_release(
            &self,
            request: tonic::Request<super::RevokeDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RevokeDatasetReleaseResponse>,
            tonic::Status,
        >;
        /** GetDatasetRelease reads one release.
*/
        async fn get_dataset_release(
            &self,
            request: tonic::Request<super::GetDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetDatasetReleaseResponse>,
            tonic::Status,
        >;
        /** ListDatasetReleases lists immutable releases under one dataset.
*/
        async fn list_dataset_releases(
            &self,
            request: tonic::Request<super::ListDatasetReleasesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListDatasetReleasesResponse>,
            tonic::Status,
        >;
    }
    /** DatasetService owns dataset and immutable release application RPCs.
*/
    #[derive(Debug)]
    pub struct DatasetServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> DatasetServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for DatasetServiceServer<T>
    where
        T: DatasetService,
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
                "/mindclade.internal.dataset.v1.DatasetService/CreateDataset" => {
                    #[allow(non_camel_case_types)]
                    struct CreateDatasetSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::CreateDatasetRequest>
                    for CreateDatasetSvc<T> {
                        type Response = super::CreateDatasetResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateDatasetRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::create_dataset(&inner, request).await
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
                        let method = CreateDatasetSvc(inner);
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
                "/mindclade.internal.dataset.v1.DatasetService/GetDataset" => {
                    #[allow(non_camel_case_types)]
                    struct GetDatasetSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::GetDatasetRequest>
                    for GetDatasetSvc<T> {
                        type Response = super::GetDatasetResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetDatasetRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::get_dataset(&inner, request).await
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
                        let method = GetDatasetSvc(inner);
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
                "/mindclade.internal.dataset.v1.DatasetService/ListDatasets" => {
                    #[allow(non_camel_case_types)]
                    struct ListDatasetsSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::ListDatasetsRequest>
                    for ListDatasetsSvc<T> {
                        type Response = super::ListDatasetsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListDatasetsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::list_datasets(&inner, request).await
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
                        let method = ListDatasetsSvc(inner);
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
                "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset" => {
                    #[allow(non_camel_case_types)]
                    struct UpdateDatasetSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::UpdateDatasetRequest>
                    for UpdateDatasetSvc<T> {
                        type Response = super::UpdateDatasetResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::UpdateDatasetRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::update_dataset(&inner, request).await
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
                        let method = UpdateDatasetSvc(inner);
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
                "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease" => {
                    #[allow(non_camel_case_types)]
                    struct PublishDatasetReleaseSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::PublishDatasetReleaseRequest>
                    for PublishDatasetReleaseSvc<T> {
                        type Response = super::PublishDatasetReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::PublishDatasetReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::publish_dataset_release(
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
                        let method = PublishDatasetReleaseSvc(inner);
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
                "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease" => {
                    #[allow(non_camel_case_types)]
                    struct RevokeDatasetReleaseSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::RevokeDatasetReleaseRequest>
                    for RevokeDatasetReleaseSvc<T> {
                        type Response = super::RevokeDatasetReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::RevokeDatasetReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::revoke_dataset_release(
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
                        let method = RevokeDatasetReleaseSvc(inner);
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
                "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease" => {
                    #[allow(non_camel_case_types)]
                    struct GetDatasetReleaseSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::GetDatasetReleaseRequest>
                    for GetDatasetReleaseSvc<T> {
                        type Response = super::GetDatasetReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetDatasetReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::get_dataset_release(&inner, request)
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
                        let method = GetDatasetReleaseSvc(inner);
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
                "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases" => {
                    #[allow(non_camel_case_types)]
                    struct ListDatasetReleasesSvc<T: DatasetService>(pub Arc<T>);
                    impl<
                        T: DatasetService,
                    > tonic::server::UnaryService<super::ListDatasetReleasesRequest>
                    for ListDatasetReleasesSvc<T> {
                        type Response = super::ListDatasetReleasesResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListDatasetReleasesRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as DatasetService>::list_dataset_releases(
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
                        let method = ListDatasetReleasesSvc(inner);
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
    impl<T> Clone for DatasetServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.dataset.v1.DatasetService";
    impl<T> tonic::server::NamedService for DatasetServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
