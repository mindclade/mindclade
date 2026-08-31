// @generated
/// Generated client implementations.
pub mod mindclade_service_client {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    use tonic::codegen::http::Uri;
    /** MindcladeService is the curated public gRPC facade transport-equivalent to external-api.yaml.
*/
    #[derive(Debug, Clone)]
    pub struct MindcladeServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }
    impl MindcladeServiceClient<tonic::transport::Channel> {
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
    impl<T> MindcladeServiceClient<T>
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
        ) -> MindcladeServiceClient<InterceptedService<T, F>>
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
            MindcladeServiceClient::new(InterceptedService::new(inner, interceptor))
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
        /** SubmitInference maps the submitInference HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/SubmitInference",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "SubmitInference",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetOperation maps the getOperation HTTP operation.
*/
        pub async fn get_operation(
            &mut self,
            request: impl tonic::IntoRequest<super::GetOperationRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetOperationResponse>,
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
                "/mindclade.api.v1.MindcladeService/GetOperation",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "GetOperation"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CancelOperation maps the cancelOperation HTTP operation.
*/
        pub async fn cancel_operation(
            &mut self,
            request: impl tonic::IntoRequest<super::CancelOperationRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelOperationResponse>,
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
                "/mindclade.api.v1.MindcladeService/CancelOperation",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CancelOperation",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetArtifact maps the getArtifact HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetArtifact",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "GetArtifact"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** DownloadArtifact maps the downloadArtifact HTTP data-plane operation.
*/
        pub async fn download_artifact(
            &mut self,
            request: impl tonic::IntoRequest<super::DownloadArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<tonic::codec::Streaming<super::DownloadArtifactResponse>>,
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
                "/mindclade.api.v1.MindcladeService/DownloadArtifact",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "DownloadArtifact",
                    ),
                );
            self.inner.server_streaming(req, path, codec).await
        }
        /** ListDatasets maps the listDatasets HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListDatasets",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "ListDatasets"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateDataset maps the createDataset HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/CreateDataset",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "CreateDataset"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetDataset maps the getDataset HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetDataset",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "GetDataset"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** UpdateDataset maps the updateDataset HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/UpdateDataset",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "UpdateDataset"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListDatasetReleases maps the listDatasetReleases HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListDatasetReleases",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListDatasetReleases",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateDatasetRelease maps the createDatasetRelease HTTP operation.
*/
        pub async fn create_dataset_release(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateDatasetReleaseResponse>,
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
                "/mindclade.api.v1.MindcladeService/CreateDatasetRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateDatasetRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListModels maps the listModels HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListModels",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "ListModels"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateModel maps the createModel HTTP operation.
*/
        pub async fn create_model(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateModelResponse>,
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
                "/mindclade.api.v1.MindcladeService/CreateModel",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "CreateModel"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetModel maps the getModel HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetModel",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "GetModel"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** UpdateModel maps the updateModel HTTP operation.
*/
        pub async fn update_model(
            &mut self,
            request: impl tonic::IntoRequest<super::UpdateModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateModelResponse>,
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
                "/mindclade.api.v1.MindcladeService/UpdateModel",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "UpdateModel"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListModelReleases maps the listModelReleases HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListModelReleases",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListModelReleases",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateModelRelease maps the createModelRelease HTTP operation.
*/
        pub async fn create_model_release(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateModelReleaseResponse>,
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
                "/mindclade.api.v1.MindcladeService/CreateModelRelease",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateModelRelease",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListTrainingRuns maps the listTrainingRuns HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListTrainingRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListTrainingRuns",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateTrainingRun maps the createTrainingRun HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/CreateTrainingRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateTrainingRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetTrainingRun maps the getTrainingRun HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetTrainingRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "GetTrainingRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListEvaluationRuns maps the listEvaluationRuns HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListEvaluationRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListEvaluationRuns",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateEvaluationRun maps the createEvaluationRun HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/CreateEvaluationRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateEvaluationRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetEvaluationRun maps the getEvaluationRun HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetEvaluationRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "GetEvaluationRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetEvaluationResult maps the getEvaluationResult HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetEvaluationResult",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "GetEvaluationResult",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListAgentDefinitions maps the listAgentDefinitions HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListAgentDefinitions",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListAgentDefinitions",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateAgentDefinition maps the createAgentDefinition HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/CreateAgentDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateAgentDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListAgentRuns maps the listAgentRuns HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListAgentRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "ListAgentRuns"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateAgentRun maps the createAgentRun HTTP operation.
*/
        pub async fn create_agent_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateAgentRunResponse>,
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
                "/mindclade.api.v1.MindcladeService/CreateAgentRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateAgentRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetAgentRun maps the getAgentRun HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetAgentRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "GetAgentRun"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListWorkflowDefinitions maps the listWorkflowDefinitions HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListWorkflowDefinitions",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListWorkflowDefinitions",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateWorkflowDefinition maps the createWorkflowDefinition HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/CreateWorkflowDefinition",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateWorkflowDefinition",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListWorkflowRuns maps the listWorkflowRuns HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListWorkflowRuns",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListWorkflowRuns",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateWorkflowRun maps the createWorkflowRun HTTP operation.
*/
        pub async fn create_workflow_run(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateWorkflowRunResponse>,
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
                "/mindclade.api.v1.MindcladeService/CreateWorkflowRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "CreateWorkflowRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetWorkflowRun maps the getWorkflowRun HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/GetWorkflowRun",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "GetWorkflowRun",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListApprovalRequests maps the listApprovalRequests HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/ListApprovalRequests",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListApprovalRequests",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** DecideApproval maps the decideApproval HTTP operation.
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
                "/mindclade.api.v1.MindcladeService/DecideApproval",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "DecideApproval",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetTenant maps the getTenant HTTP operation.
*/
        pub async fn get_tenant(
            &mut self,
            request: impl tonic::IntoRequest<super::GetTenantRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetTenantResponse>,
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
                "/mindclade.api.v1.MindcladeService/GetTenant",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "GetTenant"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListProjects maps the listProjects HTTP operation.
*/
        pub async fn list_projects(
            &mut self,
            request: impl tonic::IntoRequest<super::ListProjectsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListProjectsResponse>,
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
                "/mindclade.api.v1.MindcladeService/ListProjects",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "ListProjects"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** CreateProject maps the createProject HTTP operation.
*/
        pub async fn create_project(
            &mut self,
            request: impl tonic::IntoRequest<super::CreateProjectRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateProjectResponse>,
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
                "/mindclade.api.v1.MindcladeService/CreateProject",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "CreateProject"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** GetProject maps the getProject HTTP operation.
*/
        pub async fn get_project(
            &mut self,
            request: impl tonic::IntoRequest<super::GetProjectRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetProjectResponse>,
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
                "/mindclade.api.v1.MindcladeService/GetProject",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new("mindclade.api.v1.MindcladeService", "GetProject"),
                );
            self.inner.unary(req, path, codec).await
        }
        /** ListAuditRecords maps the listAuditRecords HTTP operation.
*/
        pub async fn list_audit_records(
            &mut self,
            request: impl tonic::IntoRequest<super::ListAuditRecordsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAuditRecordsResponse>,
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
                "/mindclade.api.v1.MindcladeService/ListAuditRecords",
            );
            let mut req = request.into_request();
            req.extensions_mut()
                .insert(
                    GrpcMethod::new(
                        "mindclade.api.v1.MindcladeService",
                        "ListAuditRecords",
                    ),
                );
            self.inner.unary(req, path, codec).await
        }
    }
}
/// Generated server implementations.
pub mod mindclade_service_server {
    #![allow(
        unused_variables,
        dead_code,
        missing_docs,
        clippy::wildcard_imports,
        clippy::let_unit_value,
    )]
    use tonic::codegen::*;
    /// Generated trait containing gRPC methods that should be implemented for use with MindcladeServiceServer.
    #[async_trait]
    pub trait MindcladeService: std::marker::Send + std::marker::Sync + 'static {
        /** SubmitInference maps the submitInference HTTP operation.
*/
        async fn submit_inference(
            &self,
            request: tonic::Request<super::SubmitInferenceRequest>,
        ) -> std::result::Result<
            tonic::Response<super::SubmitInferenceResponse>,
            tonic::Status,
        >;
        /** GetOperation maps the getOperation HTTP operation.
*/
        async fn get_operation(
            &self,
            request: tonic::Request<super::GetOperationRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetOperationResponse>,
            tonic::Status,
        >;
        /** CancelOperation maps the cancelOperation HTTP operation.
*/
        async fn cancel_operation(
            &self,
            request: tonic::Request<super::CancelOperationRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CancelOperationResponse>,
            tonic::Status,
        >;
        /** GetArtifact maps the getArtifact HTTP operation.
*/
        async fn get_artifact(
            &self,
            request: tonic::Request<super::GetArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetArtifactResponse>,
            tonic::Status,
        >;
        /// Server streaming response type for the DownloadArtifact method.
        type DownloadArtifactStream: tonic::codegen::tokio_stream::Stream<
                Item = std::result::Result<
                    super::DownloadArtifactResponse,
                    tonic::Status,
                >,
            >
            + std::marker::Send
            + 'static;
        /** DownloadArtifact maps the downloadArtifact HTTP data-plane operation.
*/
        async fn download_artifact(
            &self,
            request: tonic::Request<super::DownloadArtifactRequest>,
        ) -> std::result::Result<
            tonic::Response<Self::DownloadArtifactStream>,
            tonic::Status,
        >;
        /** ListDatasets maps the listDatasets HTTP operation.
*/
        async fn list_datasets(
            &self,
            request: tonic::Request<super::ListDatasetsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListDatasetsResponse>,
            tonic::Status,
        >;
        /** CreateDataset maps the createDataset HTTP operation.
*/
        async fn create_dataset(
            &self,
            request: tonic::Request<super::CreateDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateDatasetResponse>,
            tonic::Status,
        >;
        /** GetDataset maps the getDataset HTTP operation.
*/
        async fn get_dataset(
            &self,
            request: tonic::Request<super::GetDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetDatasetResponse>,
            tonic::Status,
        >;
        /** UpdateDataset maps the updateDataset HTTP operation.
*/
        async fn update_dataset(
            &self,
            request: tonic::Request<super::UpdateDatasetRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateDatasetResponse>,
            tonic::Status,
        >;
        /** ListDatasetReleases maps the listDatasetReleases HTTP operation.
*/
        async fn list_dataset_releases(
            &self,
            request: tonic::Request<super::ListDatasetReleasesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListDatasetReleasesResponse>,
            tonic::Status,
        >;
        /** CreateDatasetRelease maps the createDatasetRelease HTTP operation.
*/
        async fn create_dataset_release(
            &self,
            request: tonic::Request<super::CreateDatasetReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateDatasetReleaseResponse>,
            tonic::Status,
        >;
        /** ListModels maps the listModels HTTP operation.
*/
        async fn list_models(
            &self,
            request: tonic::Request<super::ListModelsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListModelsResponse>,
            tonic::Status,
        >;
        /** CreateModel maps the createModel HTTP operation.
*/
        async fn create_model(
            &self,
            request: tonic::Request<super::CreateModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateModelResponse>,
            tonic::Status,
        >;
        /** GetModel maps the getModel HTTP operation.
*/
        async fn get_model(
            &self,
            request: tonic::Request<super::GetModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetModelResponse>,
            tonic::Status,
        >;
        /** UpdateModel maps the updateModel HTTP operation.
*/
        async fn update_model(
            &self,
            request: tonic::Request<super::UpdateModelRequest>,
        ) -> std::result::Result<
            tonic::Response<super::UpdateModelResponse>,
            tonic::Status,
        >;
        /** ListModelReleases maps the listModelReleases HTTP operation.
*/
        async fn list_model_releases(
            &self,
            request: tonic::Request<super::ListModelReleasesRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListModelReleasesResponse>,
            tonic::Status,
        >;
        /** CreateModelRelease maps the createModelRelease HTTP operation.
*/
        async fn create_model_release(
            &self,
            request: tonic::Request<super::CreateModelReleaseRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateModelReleaseResponse>,
            tonic::Status,
        >;
        /** ListTrainingRuns maps the listTrainingRuns HTTP operation.
*/
        async fn list_training_runs(
            &self,
            request: tonic::Request<super::ListTrainingRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListTrainingRunsResponse>,
            tonic::Status,
        >;
        /** CreateTrainingRun maps the createTrainingRun HTTP operation.
*/
        async fn create_training_run(
            &self,
            request: tonic::Request<super::CreateTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateTrainingRunResponse>,
            tonic::Status,
        >;
        /** GetTrainingRun maps the getTrainingRun HTTP operation.
*/
        async fn get_training_run(
            &self,
            request: tonic::Request<super::GetTrainingRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetTrainingRunResponse>,
            tonic::Status,
        >;
        /** ListEvaluationRuns maps the listEvaluationRuns HTTP operation.
*/
        async fn list_evaluation_runs(
            &self,
            request: tonic::Request<super::ListEvaluationRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListEvaluationRunsResponse>,
            tonic::Status,
        >;
        /** CreateEvaluationRun maps the createEvaluationRun HTTP operation.
*/
        async fn create_evaluation_run(
            &self,
            request: tonic::Request<super::CreateEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateEvaluationRunResponse>,
            tonic::Status,
        >;
        /** GetEvaluationRun maps the getEvaluationRun HTTP operation.
*/
        async fn get_evaluation_run(
            &self,
            request: tonic::Request<super::GetEvaluationRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetEvaluationRunResponse>,
            tonic::Status,
        >;
        /** GetEvaluationResult maps the getEvaluationResult HTTP operation.
*/
        async fn get_evaluation_result(
            &self,
            request: tonic::Request<super::GetEvaluationResultRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetEvaluationResultResponse>,
            tonic::Status,
        >;
        /** ListAgentDefinitions maps the listAgentDefinitions HTTP operation.
*/
        async fn list_agent_definitions(
            &self,
            request: tonic::Request<super::ListAgentDefinitionsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentDefinitionsResponse>,
            tonic::Status,
        >;
        /** CreateAgentDefinition maps the createAgentDefinition HTTP operation.
*/
        async fn create_agent_definition(
            &self,
            request: tonic::Request<super::CreateAgentDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateAgentDefinitionResponse>,
            tonic::Status,
        >;
        /** ListAgentRuns maps the listAgentRuns HTTP operation.
*/
        async fn list_agent_runs(
            &self,
            request: tonic::Request<super::ListAgentRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAgentRunsResponse>,
            tonic::Status,
        >;
        /** CreateAgentRun maps the createAgentRun HTTP operation.
*/
        async fn create_agent_run(
            &self,
            request: tonic::Request<super::CreateAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateAgentRunResponse>,
            tonic::Status,
        >;
        /** GetAgentRun maps the getAgentRun HTTP operation.
*/
        async fn get_agent_run(
            &self,
            request: tonic::Request<super::GetAgentRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetAgentRunResponse>,
            tonic::Status,
        >;
        /** ListWorkflowDefinitions maps the listWorkflowDefinitions HTTP operation.
*/
        async fn list_workflow_definitions(
            &self,
            request: tonic::Request<super::ListWorkflowDefinitionsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListWorkflowDefinitionsResponse>,
            tonic::Status,
        >;
        /** CreateWorkflowDefinition maps the createWorkflowDefinition HTTP operation.
*/
        async fn create_workflow_definition(
            &self,
            request: tonic::Request<super::CreateWorkflowDefinitionRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateWorkflowDefinitionResponse>,
            tonic::Status,
        >;
        /** ListWorkflowRuns maps the listWorkflowRuns HTTP operation.
*/
        async fn list_workflow_runs(
            &self,
            request: tonic::Request<super::ListWorkflowRunsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListWorkflowRunsResponse>,
            tonic::Status,
        >;
        /** CreateWorkflowRun maps the createWorkflowRun HTTP operation.
*/
        async fn create_workflow_run(
            &self,
            request: tonic::Request<super::CreateWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateWorkflowRunResponse>,
            tonic::Status,
        >;
        /** GetWorkflowRun maps the getWorkflowRun HTTP operation.
*/
        async fn get_workflow_run(
            &self,
            request: tonic::Request<super::GetWorkflowRunRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetWorkflowRunResponse>,
            tonic::Status,
        >;
        /** ListApprovalRequests maps the listApprovalRequests HTTP operation.
*/
        async fn list_approval_requests(
            &self,
            request: tonic::Request<super::ListApprovalRequestsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListApprovalRequestsResponse>,
            tonic::Status,
        >;
        /** DecideApproval maps the decideApproval HTTP operation.
*/
        async fn decide_approval(
            &self,
            request: tonic::Request<super::DecideApprovalRequest>,
        ) -> std::result::Result<
            tonic::Response<super::DecideApprovalResponse>,
            tonic::Status,
        >;
        /** GetTenant maps the getTenant HTTP operation.
*/
        async fn get_tenant(
            &self,
            request: tonic::Request<super::GetTenantRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetTenantResponse>,
            tonic::Status,
        >;
        /** ListProjects maps the listProjects HTTP operation.
*/
        async fn list_projects(
            &self,
            request: tonic::Request<super::ListProjectsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListProjectsResponse>,
            tonic::Status,
        >;
        /** CreateProject maps the createProject HTTP operation.
*/
        async fn create_project(
            &self,
            request: tonic::Request<super::CreateProjectRequest>,
        ) -> std::result::Result<
            tonic::Response<super::CreateProjectResponse>,
            tonic::Status,
        >;
        /** GetProject maps the getProject HTTP operation.
*/
        async fn get_project(
            &self,
            request: tonic::Request<super::GetProjectRequest>,
        ) -> std::result::Result<
            tonic::Response<super::GetProjectResponse>,
            tonic::Status,
        >;
        /** ListAuditRecords maps the listAuditRecords HTTP operation.
*/
        async fn list_audit_records(
            &self,
            request: tonic::Request<super::ListAuditRecordsRequest>,
        ) -> std::result::Result<
            tonic::Response<super::ListAuditRecordsResponse>,
            tonic::Status,
        >;
    }
    /** MindcladeService is the curated public gRPC facade transport-equivalent to external-api.yaml.
*/
    #[derive(Debug)]
    pub struct MindcladeServiceServer<T> {
        inner: Arc<T>,
        accept_compression_encodings: EnabledCompressionEncodings,
        send_compression_encodings: EnabledCompressionEncodings,
        max_decoding_message_size: Option<usize>,
        max_encoding_message_size: Option<usize>,
    }
    impl<T> MindcladeServiceServer<T> {
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
    impl<T, B> tonic::codegen::Service<http::Request<B>> for MindcladeServiceServer<T>
    where
        T: MindcladeService,
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
                "/mindclade.api.v1.MindcladeService/SubmitInference" => {
                    #[allow(non_camel_case_types)]
                    struct SubmitInferenceSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::submit_inference(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/GetOperation" => {
                    #[allow(non_camel_case_types)]
                    struct GetOperationSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::GetOperationRequest>
                    for GetOperationSvc<T> {
                        type Response = super::GetOperationResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetOperationRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::get_operation(&inner, request)
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
                        let method = GetOperationSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/CancelOperation" => {
                    #[allow(non_camel_case_types)]
                    struct CancelOperationSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::CancelOperationRequest>
                    for CancelOperationSvc<T> {
                        type Response = super::CancelOperationResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CancelOperationRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::cancel_operation(&inner, request)
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
                        let method = CancelOperationSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/GetArtifact" => {
                    #[allow(non_camel_case_types)]
                    struct GetArtifactSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_artifact(&inner, request).await
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
                "/mindclade.api.v1.MindcladeService/DownloadArtifact" => {
                    #[allow(non_camel_case_types)]
                    struct DownloadArtifactSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::ServerStreamingService<
                        super::DownloadArtifactRequest,
                    > for DownloadArtifactSvc<T> {
                        type Response = super::DownloadArtifactResponse;
                        type ResponseStream = T::DownloadArtifactStream;
                        type Future = BoxFuture<
                            tonic::Response<Self::ResponseStream>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::DownloadArtifactRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::download_artifact(&inner, request)
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
                        let method = DownloadArtifactSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/ListDatasets" => {
                    #[allow(non_camel_case_types)]
                    struct ListDatasetsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_datasets(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/CreateDataset" => {
                    #[allow(non_camel_case_types)]
                    struct CreateDatasetSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::create_dataset(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/GetDataset" => {
                    #[allow(non_camel_case_types)]
                    struct GetDatasetSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_dataset(&inner, request).await
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
                "/mindclade.api.v1.MindcladeService/UpdateDataset" => {
                    #[allow(non_camel_case_types)]
                    struct UpdateDatasetSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::update_dataset(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/ListDatasetReleases" => {
                    #[allow(non_camel_case_types)]
                    struct ListDatasetReleasesSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_dataset_releases(
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
                "/mindclade.api.v1.MindcladeService/CreateDatasetRelease" => {
                    #[allow(non_camel_case_types)]
                    struct CreateDatasetReleaseSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::CreateDatasetReleaseRequest>
                    for CreateDatasetReleaseSvc<T> {
                        type Response = super::CreateDatasetReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateDatasetReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::create_dataset_release(
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
                        let method = CreateDatasetReleaseSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/ListModels" => {
                    #[allow(non_camel_case_types)]
                    struct ListModelsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_models(&inner, request).await
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
                "/mindclade.api.v1.MindcladeService/CreateModel" => {
                    #[allow(non_camel_case_types)]
                    struct CreateModelSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::CreateModelRequest>
                    for CreateModelSvc<T> {
                        type Response = super::CreateModelResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateModelRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::create_model(&inner, request).await
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
                        let method = CreateModelSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/GetModel" => {
                    #[allow(non_camel_case_types)]
                    struct GetModelSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_model(&inner, request).await
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
                "/mindclade.api.v1.MindcladeService/UpdateModel" => {
                    #[allow(non_camel_case_types)]
                    struct UpdateModelSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::UpdateModelRequest>
                    for UpdateModelSvc<T> {
                        type Response = super::UpdateModelResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::UpdateModelRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::update_model(&inner, request).await
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
                        let method = UpdateModelSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/ListModelReleases" => {
                    #[allow(non_camel_case_types)]
                    struct ListModelReleasesSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_model_releases(
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
                "/mindclade.api.v1.MindcladeService/CreateModelRelease" => {
                    #[allow(non_camel_case_types)]
                    struct CreateModelReleaseSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::CreateModelReleaseRequest>
                    for CreateModelReleaseSvc<T> {
                        type Response = super::CreateModelReleaseResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateModelReleaseRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::create_model_release(
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
                        let method = CreateModelReleaseSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/ListTrainingRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListTrainingRunsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_training_runs(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/CreateTrainingRun" => {
                    #[allow(non_camel_case_types)]
                    struct CreateTrainingRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::create_training_run(
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
                "/mindclade.api.v1.MindcladeService/GetTrainingRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetTrainingRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_training_run(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/ListEvaluationRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListEvaluationRunsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_evaluation_runs(
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
                "/mindclade.api.v1.MindcladeService/CreateEvaluationRun" => {
                    #[allow(non_camel_case_types)]
                    struct CreateEvaluationRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::create_evaluation_run(
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
                "/mindclade.api.v1.MindcladeService/GetEvaluationRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetEvaluationRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_evaluation_run(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/GetEvaluationResult" => {
                    #[allow(non_camel_case_types)]
                    struct GetEvaluationResultSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_evaluation_result(
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
                "/mindclade.api.v1.MindcladeService/ListAgentDefinitions" => {
                    #[allow(non_camel_case_types)]
                    struct ListAgentDefinitionsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_agent_definitions(
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
                "/mindclade.api.v1.MindcladeService/CreateAgentDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct CreateAgentDefinitionSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::create_agent_definition(
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
                "/mindclade.api.v1.MindcladeService/ListAgentRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListAgentRunsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_agent_runs(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/CreateAgentRun" => {
                    #[allow(non_camel_case_types)]
                    struct CreateAgentRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::CreateAgentRunRequest>
                    for CreateAgentRunSvc<T> {
                        type Response = super::CreateAgentRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateAgentRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::create_agent_run(&inner, request)
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
                        let method = CreateAgentRunSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/GetAgentRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetAgentRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_agent_run(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/ListWorkflowDefinitions" => {
                    #[allow(non_camel_case_types)]
                    struct ListWorkflowDefinitionsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_workflow_definitions(
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
                "/mindclade.api.v1.MindcladeService/CreateWorkflowDefinition" => {
                    #[allow(non_camel_case_types)]
                    struct CreateWorkflowDefinitionSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::create_workflow_definition(
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
                "/mindclade.api.v1.MindcladeService/ListWorkflowRuns" => {
                    #[allow(non_camel_case_types)]
                    struct ListWorkflowRunsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_workflow_runs(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/CreateWorkflowRun" => {
                    #[allow(non_camel_case_types)]
                    struct CreateWorkflowRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::CreateWorkflowRunRequest>
                    for CreateWorkflowRunSvc<T> {
                        type Response = super::CreateWorkflowRunResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateWorkflowRunRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::create_workflow_run(
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
                        let method = CreateWorkflowRunSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/GetWorkflowRun" => {
                    #[allow(non_camel_case_types)]
                    struct GetWorkflowRunSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::get_workflow_run(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/ListApprovalRequests" => {
                    #[allow(non_camel_case_types)]
                    struct ListApprovalRequestsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::list_approval_requests(
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
                "/mindclade.api.v1.MindcladeService/DecideApproval" => {
                    #[allow(non_camel_case_types)]
                    struct DecideApprovalSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
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
                                <T as MindcladeService>::decide_approval(&inner, request)
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
                "/mindclade.api.v1.MindcladeService/GetTenant" => {
                    #[allow(non_camel_case_types)]
                    struct GetTenantSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::GetTenantRequest>
                    for GetTenantSvc<T> {
                        type Response = super::GetTenantResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetTenantRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::get_tenant(&inner, request).await
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
                        let method = GetTenantSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/ListProjects" => {
                    #[allow(non_camel_case_types)]
                    struct ListProjectsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::ListProjectsRequest>
                    for ListProjectsSvc<T> {
                        type Response = super::ListProjectsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListProjectsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::list_projects(&inner, request)
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
                        let method = ListProjectsSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/CreateProject" => {
                    #[allow(non_camel_case_types)]
                    struct CreateProjectSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::CreateProjectRequest>
                    for CreateProjectSvc<T> {
                        type Response = super::CreateProjectResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::CreateProjectRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::create_project(&inner, request)
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
                        let method = CreateProjectSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/GetProject" => {
                    #[allow(non_camel_case_types)]
                    struct GetProjectSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::GetProjectRequest>
                    for GetProjectSvc<T> {
                        type Response = super::GetProjectResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::GetProjectRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::get_project(&inner, request).await
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
                        let method = GetProjectSvc(inner);
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
                "/mindclade.api.v1.MindcladeService/ListAuditRecords" => {
                    #[allow(non_camel_case_types)]
                    struct ListAuditRecordsSvc<T: MindcladeService>(pub Arc<T>);
                    impl<
                        T: MindcladeService,
                    > tonic::server::UnaryService<super::ListAuditRecordsRequest>
                    for ListAuditRecordsSvc<T> {
                        type Response = super::ListAuditRecordsResponse;
                        type Future = BoxFuture<
                            tonic::Response<Self::Response>,
                            tonic::Status,
                        >;
                        fn call(
                            &mut self,
                            request: tonic::Request<super::ListAuditRecordsRequest>,
                        ) -> Self::Future {
                            let inner = Arc::clone(&self.0);
                            let fut = async move {
                                <T as MindcladeService>::list_audit_records(&inner, request)
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
                        let method = ListAuditRecordsSvc(inner);
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
    impl<T> Clone for MindcladeServiceServer<T> {
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
    pub const SERVICE_NAME: &str = "mindclade.api.v1.MindcladeService";
    impl<T> tonic::server::NamedService for MindcladeServiceServer<T> {
        const NAME: &'static str = SERVICE_NAME;
    }
}
