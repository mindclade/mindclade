package experiments

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
)

type scanner interface{ Scan(...any) error }

type experimentRow struct {
	tenantID, projectID, name, uid, etag, displayName, classification string
	revision                                                          int64
	kind, state                                                       int32
	intentID, usePolicyID                                             sql.NullInt64
	createTime, updateTime                                            time.Time
	completeTime                                                      sql.NullTime
}

const experimentColumns = `tenant_id,project_id,name,uid,revision,etag,display_name,kind,state,intent_manifest_ref_id,use_policy_ref_id,policy_classification,create_time,update_time,complete_time`

func scanExperiment(row scanner) (experimentRow, error) {
	var value experimentRow
	err := row.Scan(&value.tenantID, &value.projectID, &value.name, &value.uid, &value.revision, &value.etag, &value.displayName, &value.kind, &value.state, &value.intentID, &value.usePolicyID, &value.classification, &value.createTime, &value.updateTime, &value.completeTime)
	return value, err
}

func experimentProto(ctx context.Context, tx *sql.Tx, row experimentRow) (*experimentv1.Experiment, error) {
	intent, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.intentID)
	if err != nil {
		return nil, err
	}
	policy, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.usePolicyID)
	if err != nil {
		return nil, err
	}
	labels, err := platformdb.LoadStringMap(ctx, tx, `SELECT label_key,label_value FROM experiment_labels WHERE tenant_id=$1 AND project_id=$2 AND experiment_name=$3 ORDER BY label_key`, row.tenantID, row.projectID, row.name)
	if err != nil {
		return nil, err
	}
	annotations, err := platformdb.LoadStringMap(ctx, tx, `SELECT annotation_key,annotation_value FROM experiment_annotations WHERE tenant_id=$1 AND project_id=$2 AND experiment_name=$3 ORDER BY annotation_key`, row.tenantID, row.projectID, row.name)
	if err != nil {
		return nil, err
	}
	subjectIDs, err := loadSubjectIDs(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	// pgx's database/sql driver does not permit a second statement while a
	// rows iterator is active on the transaction connection. Materialize the
	// ordered foreign keys first, close the cursor, and only then resolve the
	// normalized resource references.
	subjects := make([]*commonv1.ResourceRef, 0, len(subjectIDs))
	for _, id := range subjectIDs {
		subject, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenantID, id)
		if loadErr != nil {
			return nil, loadErr
		}
		subjects = append(subjects, subject)
	}
	value := &experimentv1.Experiment{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		TenantName: "tenants/" + row.tenantID, ProjectName: projectParent(Identity{TenantID: row.tenantID, ProjectID: row.projectID}),
		DisplayName: row.displayName, Labels: labels, Annotations: annotations,
		Kind: experimentv1.ExperimentKind(row.kind), State: experimentv1.ExperimentState(row.state),
		IntentManifest: intent, Subjects: subjects, UsePolicy: policy, PolicyClassification: row.classification,
		CreateTime: timestamppb.New(row.createTime.UTC()), UpdateTime: timestamppb.New(row.updateTime.UTC()),
	}
	if row.completeTime.Valid {
		value.CompleteTime = timestamppb.New(row.completeTime.Time.UTC())
	}
	return value, nil
}

func loadSubjectIDs(ctx context.Context, tx *sql.Tx, row experimentRow) ([]sql.NullInt64, error) {
	rows, err := tx.QueryContext(ctx, `SELECT subject_ref_id FROM experiment_subjects WHERE tenant_id=$1 AND project_id=$2 AND experiment_name=$3 ORDER BY ordinal`, row.tenantID, row.projectID, row.name)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	result := make([]sql.NullInt64, 0)
	for rows.Next() {
		var id sql.NullInt64
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		result = append(result, id)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

type studyRow struct {
	tenantID, projectID, name, uid, experimentName, etag string
	revision                                             int64
	studyType, state                                     int32
	experimentID, manifestID, baseID, searchID, objectID sql.NullInt64
	maximumTrials, maximumParallel                       int64
	durationSeconds                                      int64
	durationNanos                                        int32
	createTime                                           time.Time
	startTime, completeTime                              sql.NullTime
}

const studyColumns = `tenant_id,project_id,name,uid,experiment_name,experiment_ref_id,revision,etag,study_type,state,study_manifest_ref_id,base_configuration_ref_id,search_space_ref_id,objective_specification_ref_id,maximum_trials,maximum_parallel_trials,maximum_duration_seconds,maximum_duration_nanos,create_time,start_time,complete_time`

func scanStudy(row scanner) (studyRow, error) {
	var value studyRow
	err := row.Scan(&value.tenantID, &value.projectID, &value.name, &value.uid, &value.experimentName, &value.experimentID, &value.revision, &value.etag, &value.studyType, &value.state, &value.manifestID, &value.baseID, &value.searchID, &value.objectID, &value.maximumTrials, &value.maximumParallel, &value.durationSeconds, &value.durationNanos, &value.createTime, &value.startTime, &value.completeTime)
	return value, err
}

func studyProto(ctx context.Context, tx *sql.Tx, row studyRow) (*experimentv1.Study, error) {
	experiment, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.experimentID)
	if err != nil {
		return nil, err
	}
	refs := make([]*artifactv1.ArtifactRef, 4)
	for index, id := range []sql.NullInt64{row.manifestID, row.baseID, row.searchID, row.objectID} {
		refs[index], err = platformdb.LoadArtifactRef(ctx, tx, row.tenantID, id)
		if err != nil {
			return nil, err
		}
	}
	maximumTrials, err := numconv.Int64ToUint32(row.maximumTrials)
	if err != nil {
		return nil, err
	}
	maximumParallel, err := numconv.Int64ToUint32(row.maximumParallel)
	if err != nil {
		return nil, err
	}
	var admitted, completed int64
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FILTER (WHERE state >= 2),count(*) FILTER (WHERE state BETWEEN 4 AND 7) FROM experiment_trials WHERE tenant_id=$1 AND project_id=$2 AND study_name=$3`, row.tenantID, row.projectID, row.name).Scan(&admitted, &completed); err != nil {
		return nil, err
	}
	admittedCount, err := numconv.Int64ToUint32(admitted)
	if err != nil {
		return nil, err
	}
	completedCount, err := numconv.Int64ToUint32(completed)
	if err != nil {
		return nil, err
	}
	value := &experimentv1.Study{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		TenantName: "tenants/" + row.tenantID, ProjectName: projectParent(Identity{TenantID: row.tenantID, ProjectID: row.projectID}),
		Experiment: experiment, Type: experimentv1.StudyType(row.studyType), State: experimentv1.StudyState(row.state),
		StudyManifest: refs[0], BaseConfiguration: refs[1], SearchSpace: refs[2], ObjectiveSpecification: refs[3],
		Budget:             &experimentv1.StudyBudget{MaximumTrials: maximumTrials, MaximumParallelTrials: maximumParallel, MaximumDuration: durationpb.New(time.Duration(row.durationSeconds)*time.Second + time.Duration(row.durationNanos))},
		AdmittedTrialCount: admittedCount, CompletedTrialCount: completedCount, CreateTime: timestamppb.New(row.createTime.UTC()),
	}
	if row.startTime.Valid {
		value.StartTime = timestamppb.New(row.startTime.Time.UTC())
	}
	if row.completeTime.Valid {
		value.CompleteTime = timestamppb.New(row.completeTime.Time.UTC())
	}
	return value, nil
}

type trialRow struct {
	tenantID, projectID, name, uid, studyName, etag string
	revision                                        int64
	studyID                                         sql.NullInt64
	trialNumber                                     int64
	state, outcome                                  int32
	configurationID, executionID, resultID, errorID sql.NullInt64
	createTime                                      time.Time
	startTime, completeTime                         sql.NullTime
	elapsedSeconds                                  sql.NullInt64
	elapsedNanos                                    sql.NullInt32
}

const trialColumns = `tenant_id,project_id,name,uid,study_name,study_ref_id,revision,etag,trial_number,state,outcome,resolved_configuration_ref_id,execution_ref_id,result_manifest_ref_id,error_detail_id,create_time,start_time,complete_time,elapsed_seconds,elapsed_nanos`

func scanTrial(row scanner) (trialRow, error) {
	var value trialRow
	err := row.Scan(&value.tenantID, &value.projectID, &value.name, &value.uid, &value.studyName, &value.studyID, &value.revision, &value.etag, &value.trialNumber, &value.state, &value.outcome, &value.configurationID, &value.executionID, &value.resultID, &value.errorID, &value.createTime, &value.startTime, &value.completeTime, &value.elapsedSeconds, &value.elapsedNanos)
	return value, err
}

func trialProto(ctx context.Context, tx *sql.Tx, row trialRow) (*experimentv1.Trial, error) {
	study, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.studyID)
	if err != nil {
		return nil, err
	}
	configuration, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.configurationID)
	if err != nil {
		return nil, err
	}
	execution, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.executionID)
	if err != nil {
		return nil, err
	}
	result, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.resultID)
	if err != nil {
		return nil, err
	}
	failure, err := platformdb.LoadErrorDetail(ctx, tx, row.tenantID, row.errorID)
	if err != nil {
		return nil, err
	}
	trialNumber, err := numconv.Int64ToUint32(row.trialNumber)
	if err != nil {
		return nil, err
	}
	evidenceRows, err := tx.QueryContext(ctx, `SELECT digest,subject_digest,evidence_kind,policy_digest FROM experiment_trial_evidence WHERE tenant_id=$1 AND project_id=$2 AND trial_name=$3 ORDER BY ordinal`, row.tenantID, row.projectID, row.name)
	if err != nil {
		return nil, err
	}
	defer func() { _ = evidenceRows.Close() }()
	evidence := make([]*artifactv1.EvidenceRef, 0)
	for evidenceRows.Next() {
		value := new(artifactv1.EvidenceRef)
		if err = evidenceRows.Scan(&value.Digest, &value.SubjectDigest, &value.EvidenceKind, &value.PolicyDigest); err != nil {
			return nil, err
		}
		evidence = append(evidence, value)
	}
	if err = evidenceRows.Err(); err != nil {
		return nil, err
	}
	value := &experimentv1.Trial{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		TenantName: "tenants/" + row.tenantID, ProjectName: projectParent(Identity{TenantID: row.tenantID, ProjectID: row.projectID}),
		Study: study, TrialNumber: trialNumber, State: experimentv1.TrialState(row.state), Outcome: experimentv1.TrialOutcome(row.outcome),
		ResolvedConfiguration: configuration, Execution: execution, ResultManifest: result, Evidence: evidence, Error: failure,
		CreateTime: timestamppb.New(row.createTime.UTC()),
	}
	if row.startTime.Valid {
		value.StartTime = timestamppb.New(row.startTime.Time.UTC())
	}
	if row.completeTime.Valid {
		value.CompleteTime = timestamppb.New(row.completeTime.Time.UTC())
	}
	if row.elapsedSeconds.Valid && row.elapsedNanos.Valid {
		value.ElapsedTime = durationpb.New(time.Duration(row.elapsedSeconds.Int64)*time.Second + time.Duration(row.elapsedNanos.Int32))
	}
	return value, nil
}

func mapNotFound(err error) error {
	if errors.Is(err, sql.ErrNoRows) {
		return ErrNotFound
	}
	return err
}
