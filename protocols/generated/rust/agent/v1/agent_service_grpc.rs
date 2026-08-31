// @generated
/// Generated client implementations.
pub mod agent_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** AgentService owns definitions, durable runs, steps, and tool-receipt publication.
*/
    #[derive(Debug, Clone)]
    pub struct AgentServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl AgentServiceClient<tonic::transport::Channel> {
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
    impl<T> AgentServiceClient<T>
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
        ) -> AgentServiceClient<InterceptedService<T, F>>
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
            AgentServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** CreateAgentDefinition verifies artifact, workflow, tool, and policy references.
*/
        pub async fn create_agent_definition(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateAgentDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateAgentDefinitionResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "CreateAgentDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** UpdateAgentDefinition applies only masked mutable fields under an ETag.
*/
        pub async fn update_agent_definition(
            &mut self,
            request: impl tonic::IntoRequest<super::UpdateAgentDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateAgentDefinitionResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "UpdateAgentDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetAgentDefinition reads one definition revision.
*/
        pub async fn get_agent_definition(
            &mut self,
            request: impl tonic::IntoRequest<super::GetAgentDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetAgentDefinitionResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "GetAgentDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListAgentDefinitions returns a bounded project-scoped page.
*/
        pub async fn list_agent_definitions(
            &mut self,
            request: impl tonic::IntoRequest<super::ListAgentDefinitionsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentDefinitionsResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "ListAgentDefinitions",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** StartAgentRun admits immutable intent and returns durable asynchronous state.
*/
        pub async fn start_agent_run(
            &mut self,
            request: impl tonic::IntoRequest<super::StartAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::StartAgentRunResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/StartAgentRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "StartAgentRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetAgentRun reads one durable run.
*/
        pub async fn get_agent_run(
            &mut self,
            request: impl tonic::IntoRequest<super::GetAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetAgentRunResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/GetAgentRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "GetAgentRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListAgentRuns returns a bounded authorization-filtered page.
*/
        pub async fn list_agent_runs(
            &mut self,
            request: impl tonic::IntoRequest<super::ListAgentRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentRunsResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/ListAgentRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "ListAgentRuns",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CancelAgentRun records monotonic cancellation under optimistic concurrency.
*/
        pub async fn cancel_agent_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CancelAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelAgentRunResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/CancelAgentRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "CancelAgentRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetAgentStep reads one append-only step.
*/
        pub async fn get_agent_step(
            &mut self,
            request: impl tonic::IntoRequest<super::GetAgentStepRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetAgentStepResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/GetAgentStep",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "GetAgentStep",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListAgentSteps returns ordered, resumable run history.
*/
        pub async fn list_agent_steps(
            &mut self,
            request: impl tonic::IntoRequest<super::ListAgentStepsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentStepsResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/ListAgentSteps",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "ListAgentSteps",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CommitToolReceipt rejects stale attempts and treats receipts as execution evidence.
*/
        pub async fn commit_tool_receipt(
            &mut self,
            request: impl tonic::IntoRequest<super::CommitToolReceiptRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitToolReceiptResponse>,
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
                "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.internal.agent.v1.AgentService",
                        "CommitToolReceipt",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod agent_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with AgentServiceServer.
    #[async_trait]
    pub trait AgentService: std::marker::Send + std::marker::Sync + 'static {
        /** CreateAgentDefinition verifies artifact, workflow, tool, and policy references.
*/
        async fn create_agent_definition(
            &self,
            request: tonic::Request<super::CreateAgentDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateAgentDefinitionResponse>,
            tonic::Status,
        >;
        /** UpdateAgentDefinition applies only masked mutable fields under an ETag.
*/
        async fn update_agent_definition(
            &self,
            request: tonic::Request<super::UpdateAgentDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateAgentDefinitionResponse>,
            tonic::Status,
        >;
        /** GetAgentDefinition reads one definition revision.
*/
        async fn get_agent_definition(
            &self,
            request: tonic::Request<super::GetAgentDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetAgentDefinitionResponse>,
            tonic::Status,
        >;
        /** ListAgentDefinitions returns a bounded project-scoped page.
*/
        async fn list_agent_definitions(
            &self,
            request: tonic::Request<super::ListAgentDefinitionsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentDefinitionsResponse>,
            tonic::Status,
        >;
        /** StartAgentRun admits immutable intent and returns durable asynchronous state.
*/
        async fn start_agent_run(
            &self,
            request: tonic::Request<super::StartAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::StartAgentRunResponse>,
            tonic::Status,
        >;
        /** GetAgentRun reads one durable run.
*/
        async fn get_agent_run(
            &self,
            request: tonic::Request<super::GetAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetAgentRunResponse>,
            tonic::Status,
        >;
        /** ListAgentRuns returns a bounded authorization-filtered page.
*/
        async fn list_agent_runs(
            &self,
            request: tonic::Request<super::ListAgentRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentRunsResponse>,
            tonic::Status,
        >;
        /** CancelAgentRun records monotonic cancellation under optimistic concurrency.
*/
        async fn cancel_agent_run(
            &self,
            request: tonic::Request<super::CancelAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelAgentRunResponse>,
            tonic::Status,
        >;
        /** GetAgentStep reads one append-only step.
*/
        async fn get_agent_step(
            &self,
            request: tonic::Request<super::GetAgentStepRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetAgentStepResponse>,
            tonic::Status,
        >;
        /** ListAgentSteps returns ordered, resumable run history.
*/
        async fn list_agent_steps(
            &self,
            request: tonic::Request<super::ListAgentStepsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentStepsResponse>,
            tonic::Status,
        >;
        /** CommitToolReceipt rejects stale attempts and treats receipts as execution evidence.
*/
        async fn commit_tool_receipt(
            &self,
            request: tonic::Request<super::CommitToolReceiptRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CommitToolReceiptResponse>,
            tonic::Status,
        >;
    }
    /** AgentService owns definitions, durable runs, steps, and tool-receipt publication.
*/
    #[derive(Debug)]
    pub struct AgentServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> AgentServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for AgentServiceServer<T>
    where
        T: AgentService,
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
                "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct CreateAgentDefinitionSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::CreateAgentDefinitionRequest>
                    for CreateAgentDefinitionSvc<T> {
                        type Response = super::CreateAgentDefinitionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateAgentDefinitionRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::create_agent_definition(
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
                        let method = CreateAgentDefinitionSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct UpdateAgentDefinitionSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::UpdateAgentDefinitionRequest>
                    for UpdateAgentDefinitionSvc<T> {
                        type Response = super::UpdateAgentDefinitionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::UpdateAgentDefinitionRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::update_agent_definition(
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
                        let method = UpdateAgentDefinitionSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct GetAgentDefinitionSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::GetAgentDefinitionRequest>
                    for GetAgentDefinitionSvc<T> {
                        type Response = super::GetAgentDefinitionResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetAgentDefinitionRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::get_agent_definition(&inner, request)
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
                        let method = GetAgentDefinitionSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions" => {
                    #[allow(non_camel_case_types)]
                    struct ListAgentDefinitionsSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::ListAgentDefinitionsRequest>
                    for ListAgentDefinitionsSvc<T> {
                        type Response = super::ListAgentDefinitionsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListAgentDefinitionsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::list_agent_definitions(&inner, request)
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
                        let method = ListAgentDefinitionsSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/StartAgentRun" => {
                    #[allow(non_camel_case_types)]
                    struct StartAgentRunSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::StartAgentRunRequest>
                    for StartAgentRunSvc<T> {
                        type Response = super::StartAgentRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::StartAgentRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::start_agent_run(&inner, request).await
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
                        let method = StartAgentRunSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/GetAgentRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetAgentRunSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::GetAgentRunRequest>
                    for GetAgentRunSvc<T> {
                        type Response = super::GetAgentRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetAgentRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::get_agent_run(&inner, request).await
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
                        let method = GetAgentRunSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/ListAgentRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListAgentRunsSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::ListAgentRunsRequest>
                    for ListAgentRunsSvc<T> {
                        type Response = super::ListAgentRunsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListAgentRunsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::list_agent_runs(&inner, request).await
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
                        let method = ListAgentRunsSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/CancelAgentRun" => {
                    #[allow(non_camel_case_types)]
                    struct CancelAgentRunSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::CancelAgentRunRequest>
                    for CancelAgentRunSvc<T> {
                        type Response = super::CancelAgentRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CancelAgentRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::cancel_agent_run(&inner, request).await
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
                        let method = CancelAgentRunSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/GetAgentStep" => {
                    #[allow(non_camel_case_types)]
                    struct GetAgentStepSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::GetAgentStepRequest>
                    for GetAgentStepSvc<T> {
                        type Response = super::GetAgentStepResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetAgentStepRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::get_agent_step(&inner, request).await
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
                        let method = GetAgentStepSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/ListAgentSteps" => {
                    #[allow(non_camel_case_types)]
                    struct ListAgentStepsSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::ListAgentStepsRequest>
                    for ListAgentStepsSvc<T> {
                        type Response = super::ListAgentStepsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListAgentStepsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::list_agent_steps(&inner, request).await
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
                        let method = ListAgentStepsSvc(inner);
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
                "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt" => {
                    #[allow(non_camel_case_types)]
                    struct CommitToolReceiptSvc<T: AgentService>(pub Arc<T>);
                    impl<
                        T: AgentService,
                    > tonic::server::UnaryService<super::CommitToolReceiptRequest>
                    for CommitToolReceiptSvc<T> {
                        type Response = super::CommitToolReceiptResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CommitToolReceiptRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as AgentService>::commit_tool_receipt(&inner, request)
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
                        let method = CommitToolReceiptSvc(inner);
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
    impl<T> Clone for AgentServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.internal.agent.v1.AgentService";
    impl<T> tonic::server::NamedService for AgentServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
