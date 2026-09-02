// @generated
/// Generated client implementations.
pub mod inference_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** InferenceService owns internal submission, terminal-result, and resumable-stream RPCs.
*/
    #[derive(Debug, Clone)]
    pub struct InferenceServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl InferenceServiceClient<tonic::transport::Channel> {
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
    impl<T> InferenceServiceClient<T>
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
        ) -> InferenceServiceClient<InterceptedService<T, F>>
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
            InferenceServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** SubmitInference validates idempotency and returns durable asynchronous state.
*/
        pub async fn submit_inference(
            &mut self,
            request: impl tonic::IntoRequest<super::SubmitInferenceRequest>,
        ) -> std::result::Result<
            tonic::Response<super::SubmitInferenceResponse>,
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
                "/mindclade.internal.inference.v1.InferenceService/SubmitInference",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.inference.v1.InferenceService",
                        "SubmitInference",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetInferenceRequest returns immutable execution intent to authorized workers.
*/
        pub async fn get_inference_request(
            &mut self,
            request: impl tonic::IntoRequest<super::GetInferenceRequestRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetInferenceRequestResponse>,
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
                "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.inference.v1.InferenceService",
                        "GetInferenceRequest",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetInferenceResult reads a terminal result without reconstructing it from stream state.
*/
        pub async fn get_inference_result(
            &mut self,
            request: impl tonic::IntoRequest<super::GetInferenceResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetInferenceResultResponse>,
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
                "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.inference.v1.InferenceService",
                        "GetInferenceResult",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CommitInferenceResult rejects stale attempts and atomically publishes terminal truth.
*/
        pub async fn commit_inference_result(
            &mut self,
            request: impl tonic::IntoRequest<super::CommitInferenceResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitInferenceResultResponse>,
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
                "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.inference.v1.InferenceService",
                        "CommitInferenceResult",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** WatchInference streams resumable convenience updates over durable operation state.
*/
        pub async fn watch_inference(
            &mut self,
            request: impl tonic::IntoRequest<super::WatchInferenceRequest>,
        ) -> std::result::Result<
            tonic::Response<tonic::codec::Streaming<super::WatchInferenceResponse>>,
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
                "/mindclade.internal.inference.v1.InferenceService/WatchInference",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.inference.v1.InferenceService",
                        "WatchInference",
                    ),
                );
            self.inner.server_streaming(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod inference_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with InferenceServiceServer.
    #[async_trait]
    pub trait InferenceService: std::marker::Send + std::marker::Sync + 'static {
        /** SubmitInference validates idempotency and returns durable asynchronous state.
*/
        async fn submit_inference(
            &self,
            request: tonic::Request<super::SubmitInferenceRequest>,
        ) -> std::result::Result<
            tonic::Response<super::SubmitInferenceResponse>,
            tonic::Status,
        >;
        /** GetInferenceRequest returns immutable execution intent to authorized workers.
*/
        async fn get_inference_request(
            &self,
            request: tonic::Request<super::GetInferenceRequestRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetInferenceRequestResponse>,
            tonic::Status,
        >;
        /** GetInferenceResult reads a terminal result without reconstructing it from stream state.
*/
        async fn get_inference_result(
            &self,
            request: tonic::Request<super::GetInferenceResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetInferenceResultResponse>,
            tonic::Status,
        >;
        /** CommitInferenceResult rejects stale attempts and atomically publishes terminal truth.
*/
        async fn commit_inference_result(
            &self,
            request: tonic::Request<super::CommitInferenceResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitInferenceResultResponse>,
            tonic::Status,
        >;
        /// Server streaming response type for the WatchInference method.
        type WatchInferenceStream: tonic::codegen::tokio_stream::Stream<
                Item = std::result::Result<super::WatchInferenceResponse, tonic::Status>,
            >
            + std::marker::Send
            + 'static;
        /** WatchInference streams resumable convenience updates over durable operation state.
*/
        async fn watch_inference(
            &self,
            request: tonic::Request<super::WatchInferenceRequest>,
        ) -> std::result::Result<
            tonic::Response<Self::WatchInferenceStream>,
            tonic::Status,
        >;
    }
    /** InferenceService owns internal submission, terminal-result, and resumable-stream RPCs.
*/
    #[derive(Debug)]
    pub struct InferenceServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> InferenceServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for InferenceServiceServer<T>
    where
        T: InferenceService,
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
                "/mindclade.internal.inference.v1.InferenceService/SubmitInference" => {
                    #[allow(non_camel_case_types)]
                    struct SubmitInferenceSvc<T: InferenceService>(pub Arc<T>);
                    impl<
                        T: InferenceService,
                    > tonic::server::UnaryService<super::SubmitInferenceRequest>
                    for SubmitInferenceSvc<T> {
                        type Response = super::SubmitInferenceResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::SubmitInferenceRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as InferenceService>::submit_inference(&inner, request)
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
                        let method = SubmitInferenceSvc(inner);
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
                "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest" => {
                    #[allow(non_camel_case_types)]
                    struct GetInferenceRequestSvc<T: InferenceService>(pub Arc<T>);
                    impl<
                        T: InferenceService,
                    > tonic::server::UnaryService<super::GetInferenceRequestRequest>
                    for GetInferenceRequestSvc<T> {
                        type Response = super::GetInferenceRequestResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetInferenceRequestRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as InferenceService>::get_inference_request(
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
                        let method = GetInferenceRequestSvc(inner);
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
                "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult" => {
                    #[allow(non_camel_case_types)]
                    struct GetInferenceResultSvc<T: InferenceService>(pub Arc<T>);
                    impl<
                        T: InferenceService,
                    > tonic::server::UnaryService<super::GetInferenceResultRequest>
                    for GetInferenceResultSvc<T> {
                        type Response = super::GetInferenceResultResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetInferenceResultRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as InferenceService>::get_inference_result(
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
                        let method = GetInferenceResultSvc(inner);
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
                "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult" => {
                    #[allow(non_camel_case_types)]
                    struct CommitInferenceResultSvc<T: InferenceService>(pub Arc<T>);
                    impl<
                        T: InferenceService,
                    > tonic::server::UnaryService<super::CommitInferenceResultRequest>
                    for CommitInferenceResultSvc<T> {
                        type Response = super::CommitInferenceResultResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CommitInferenceResultRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as InferenceService>::commit_inference_result(
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
                        let method = CommitInferenceResultSvc(inner);
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
                "/mindclade.internal.inference.v1.InferenceService/WatchInference" => {
                    #[allow(non_camel_case_types)]
                    struct WatchInferenceSvc<T: InferenceService>(pub Arc<T>);
                    impl<
                        T: InferenceService,
                    > tonic::server::ServerStreamingService<super::WatchInferenceRequest>
                    for WatchInferenceSvc<T> {
                        type Response = super::WatchInferenceResponse;
                        type ResponseStream = T::WatchInferenceStream;
                        type Future = BoxFuture<
                            tonic::Response<Self::ResponseStream>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::WatchInferenceRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as InferenceService>::watch_inference(&inner, request)
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
                        let method = WatchInferenceSvc(inner);
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
    impl<T> Clone for InferenceServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.inference.v1.InferenceService";
    impl<T> tonic::server::NamedService for InferenceServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
