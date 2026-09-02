// @generated
/// Generated client implementations.
pub mod policy_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** PolicyService owns fail-closed authorization and use-policy lifecycle RPCs.
*/
    #[derive(Debug, Clone)]
    pub struct PolicyServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl PolicyServiceClient<tonic::transport::Channel> {
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
    impl<T> PolicyServiceClient<T>
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
        ) -> PolicyServiceClient<InterceptedService<T, F>>
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
            PolicyServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** EvaluateAuthorization returns an evidence-bearing decision for exact intent.
*/
        pub async fn evaluate_authorization(
            &mut self,
            request: impl tonic::IntoRequest<super::EvaluateAuthorizationRequest>,
        ) -> std::result::Result<
            tonic::Response<super::EvaluateAuthorizationResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "EvaluateAuthorization",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateUsePolicy validates the referenced interoperable policy document.
*/
        pub async fn create_use_policy(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateUsePolicyResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "CreateUsePolicy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** UpdateUsePolicy applies only masked metadata under optimistic concurrency.
*/
        pub async fn update_use_policy(
            &mut self,
            request: impl tonic::IntoRequest<super::UpdateUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateUsePolicyResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "UpdateUsePolicy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetUsePolicy reads one policy revision.
*/
        pub async fn get_use_policy(
            &mut self,
            request: impl tonic::IntoRequest<super::GetUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetUsePolicyResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "GetUsePolicy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListUsePolicies returns a bounded authorization-filtered page.
*/
        pub async fn list_use_policies(
            &mut self,
            request: impl tonic::IntoRequest<super::ListUsePoliciesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListUsePoliciesResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "ListUsePolicies",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ActivateUsePolicy creates the exact immutable snapshot used by decisions.
*/
        pub async fn activate_use_policy(
            &mut self,
            request: impl tonic::IntoRequest<super::ActivateUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ActivateUsePolicyResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "ActivateUsePolicy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** RevokeUsePolicy makes subsequent evaluations fail closed.
*/
        pub async fn revoke_use_policy(
            &mut self,
            request: impl tonic::IntoRequest<super::RevokeUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RevokeUsePolicyResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "RevokeUsePolicy",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ResolvePolicySnapshot resolves an exact version rather than mutable latest state.
*/
        pub async fn resolve_policy_snapshot(
            &mut self,
            request: impl tonic::IntoRequest<super::ResolvePolicySnapshotRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ResolvePolicySnapshotResponse>,
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
                "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.policy.v1.PolicyService",
                        "ResolvePolicySnapshot",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod policy_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with PolicyServiceServer.
    #[async_trait]
    pub trait PolicyService: std::marker::Send + std::marker::Sync + 'static {
        /** EvaluateAuthorization returns an evidence-bearing decision for exact intent.
*/
        async fn evaluate_authorization(
            &self,
            request: tonic::Request<super::EvaluateAuthorizationRequest>,
        ) -> std::result::Result<
            tonic::Response<super::EvaluateAuthorizationResponse>,
            tonic::Status,
        >;
        /** CreateUsePolicy validates the referenced interoperable policy document.
*/
        async fn create_use_policy(
            &self,
            request: tonic::Request<super::CreateUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateUsePolicyResponse>,
            tonic::Status,
        >;
        /** UpdateUsePolicy applies only masked metadata under optimistic concurrency.
*/
        async fn update_use_policy(
            &self,
            request: tonic::Request<super::UpdateUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateUsePolicyResponse>,
            tonic::Status,
        >;
        /** GetUsePolicy reads one policy revision.
*/
        async fn get_use_policy(
            &self,
            request: tonic::Request<super::GetUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetUsePolicyResponse>,
            tonic::Status,
        >;
        /** ListUsePolicies returns a bounded authorization-filtered page.
*/
        async fn list_use_policies(
            &self,
            request: tonic::Request<super::ListUsePoliciesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListUsePoliciesResponse>,
            tonic::Status,
        >;
        /** ActivateUsePolicy creates the exact immutable snapshot used by decisions.
*/
        async fn activate_use_policy(
            &self,
            request: tonic::Request<super::ActivateUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ActivateUsePolicyResponse>,
            tonic::Status,
        >;
        /** RevokeUsePolicy makes subsequent evaluations fail closed.
*/
        async fn revoke_use_policy(
            &self,
            request: tonic::Request<super::RevokeUsePolicyRequest>,
        ) -> std::result::Result<
            tonic::Response<super::RevokeUsePolicyResponse>,
            tonic::Status,
        >;
        /** ResolvePolicySnapshot resolves an exact version rather than mutable latest state.
*/
        async fn resolve_policy_snapshot(
            &self,
            request: tonic::Request<super::ResolvePolicySnapshotRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ResolvePolicySnapshotResponse>,
            tonic::Status,
        >;
    }
    /** PolicyService owns fail-closed authorization and use-policy lifecycle RPCs.
*/
    #[derive(Debug)]
    pub struct PolicyServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> PolicyServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for PolicyServiceServer<T>
    where
        T: PolicyService,
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
                "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization" => {
                    #[allow(non_camel_case_types)]
                    struct EvaluateAuthorizationSvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::EvaluateAuthorizationRequest>
                    for EvaluateAuthorizationSvc<T> {
                        type Response = super::EvaluateAuthorizationResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::EvaluateAuthorizationRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::evaluate_authorization(
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
                        let method = EvaluateAuthorizationSvc(inner);
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
                "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy" => {
                    #[allow(non_camel_case_types)]
                    struct CreateUsePolicySvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::CreateUsePolicyRequest>
                    for CreateUsePolicySvc<T> {
                        type Response = super::CreateUsePolicyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateUsePolicyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::create_use_policy(&inner, request)
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
                        let method = CreateUsePolicySvc(inner);
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
                "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy" => {
                    #[allow(non_camel_case_types)]
                    struct UpdateUsePolicySvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::UpdateUsePolicyRequest>
                    for UpdateUsePolicySvc<T> {
                        type Response = super::UpdateUsePolicyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::UpdateUsePolicyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::update_use_policy(&inner, request)
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
                        let method = UpdateUsePolicySvc(inner);
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
                "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy" => {
                    #[allow(non_camel_case_types)]
                    struct GetUsePolicySvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::GetUsePolicyRequest>
                    for GetUsePolicySvc<T> {
                        type Response = super::GetUsePolicyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetUsePolicyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::get_use_policy(&inner, request).await
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
                        let method = GetUsePolicySvc(inner);
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
                "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies" => {
                    #[allow(non_camel_case_types)]
                    struct ListUsePoliciesSvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::ListUsePoliciesRequest>
                    for ListUsePoliciesSvc<T> {
                        type Response = super::ListUsePoliciesResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListUsePoliciesRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::list_use_policies(&inner, request)
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
                        let method = ListUsePoliciesSvc(inner);
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
                "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy" => {
                    #[allow(non_camel_case_types)]
                    struct ActivateUsePolicySvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::ActivateUsePolicyRequest>
                    for ActivateUsePolicySvc<T> {
                        type Response = super::ActivateUsePolicyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ActivateUsePolicyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::activate_use_policy(&inner, request)
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
                        let method = ActivateUsePolicySvc(inner);
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
                "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy" => {
                    #[allow(non_camel_case_types)]
                    struct RevokeUsePolicySvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::RevokeUsePolicyRequest>
                    for RevokeUsePolicySvc<T> {
                        type Response = super::RevokeUsePolicyResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::RevokeUsePolicyRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::revoke_use_policy(&inner, request)
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
                        let method = RevokeUsePolicySvc(inner);
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
                "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot" => {
                    #[allow(non_camel_case_types)]
                    struct ResolvePolicySnapshotSvc<T: PolicyService>(pub Arc<T>);
                    impl<
                        T: PolicyService,
                    > tonic::server::UnaryService<super::ResolvePolicySnapshotRequest>
                    for ResolvePolicySnapshotSvc<T> {
                        type Response = super::ResolvePolicySnapshotResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ResolvePolicySnapshotRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as PolicyService>::resolve_policy_snapshot(
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
                        let method = ResolvePolicySnapshotSvc(inner);
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
    impl<T> Clone for PolicyServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.policy.v1.PolicyService";
    impl<T> tonic::server::NamedService for PolicyServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
