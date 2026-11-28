-- Generated from glassflow.modules.cutting.models; do not edit by hand.

CREATE TABLE cut_audit_events (
	id VARCHAR(36) NOT NULL, 
	dataset_id VARCHAR(128) NOT NULL, 
	seq INTEGER NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	object_type VARCHAR(32) NOT NULL, 
	object_id VARCHAR(128) NOT NULL, 
	before_version INTEGER, 
	after_version INTEGER, 
	actor VARCHAR(128) NOT NULL, 
	correlation_id VARCHAR(64) NOT NULL, 
	details_json TEXT NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_cut_audit_events_dataset_id ON cut_audit_events (dataset_id);

CREATE INDEX ix_cut_audit_events_seq ON cut_audit_events (seq);

CREATE TABLE cut_datasets (
	dataset_id VARCHAR(128) NOT NULL, 
	mode VARCHAR(16) NOT NULL, 
	mutable BOOLEAN NOT NULL, 
	parent_dataset_id VARCHAR(128), 
	source_hash VARCHAR(128) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (dataset_id), 
	CONSTRAINT ck_cut_dataset_mode CHECK (mode in ('source','workspace','contest'))
);

CREATE TABLE cut_idempotency (
	dataset_id VARCHAR(128) NOT NULL, 
	operation VARCHAR(64) NOT NULL, 
	"key" VARCHAR(128) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	status_code INTEGER NOT NULL, 
	response_json TEXT NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (dataset_id, operation, "key")
);

CREATE TABLE cut_materials (
	dataset_id VARCHAR(128) NOT NULL, 
	material_id VARCHAR(128) NOT NULL, 
	name VARCHAR(256) NOT NULL, 
	thickness_mm INTEGER NOT NULL, 
	price_per_m2 VARCHAR(32) NOT NULL, 
	tempered BOOLEAN NOT NULL, 
	PRIMARY KEY (dataset_id, material_id), 
	FOREIGN KEY(dataset_id) REFERENCES cut_datasets (dataset_id)
);

CREATE TABLE cut_parts (
	id VARCHAR(36) NOT NULL, 
	dataset_id VARCHAR(128) NOT NULL, 
	part_id VARCHAR(128) NOT NULL, 
	order_id VARCHAR(128) NOT NULL, 
	material_id VARCHAR(128) NOT NULL, 
	length_mm INTEGER NOT NULL, 
	width_mm INTEGER NOT NULL, 
	premium BOOLEAN NOT NULL, 
	product_type VARCHAR(128) NOT NULL, 
	seq INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cut_part_external UNIQUE (dataset_id, part_id), 
	CONSTRAINT ck_cut_part_dims CHECK (length_mm > 0 AND width_mm > 0), 
	FOREIGN KEY(dataset_id) REFERENCES cut_datasets (dataset_id)
);

CREATE INDEX ix_cut_parts_dataset_id ON cut_parts (dataset_id);

CREATE TABLE cut_plans (
	id VARCHAR(36) NOT NULL, 
	dataset_id VARCHAR(128) NOT NULL, 
	plan_id VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	parent_plan_id VARCHAR(64), 
	parent_revision INTEGER, 
	status VARCHAR(16) NOT NULL, 
	search_status VARCHAR(24) NOT NULL, 
	stop_reason VARCHAR(24) NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	config_json TEXT NOT NULL, 
	metrics_json TEXT NOT NULL, 
	evidence_json TEXT NOT NULL, 
	issues_json TEXT NOT NULL, 
	locks_json TEXT NOT NULL, 
	inventory_token VARCHAR(64) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	committed_at VARCHAR(40), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cut_plan_revision UNIQUE (dataset_id, plan_id, revision), 
	CONSTRAINT ck_cut_plan_status CHECK (status in ('draft','validated','committed','superseded','invalid')), 
	FOREIGN KEY(dataset_id) REFERENCES cut_datasets (dataset_id)
);

CREATE INDEX ix_cut_plans_dataset_id ON cut_plans (dataset_id);

CREATE UNIQUE INDEX uq_cut_plan_active ON cut_plans (dataset_id) WHERE status = 'committed';

CREATE TABLE cut_remnants (
	id VARCHAR(36) NOT NULL, 
	dataset_id VARCHAR(128) NOT NULL, 
	remnant_id VARCHAR(128) NOT NULL, 
	material_id VARCHAR(128) NOT NULL, 
	length_mm INTEGER NOT NULL, 
	width_mm INTEGER NOT NULL, 
	age_days INTEGER, 
	defect BOOLEAN NOT NULL, 
	location_raw VARCHAR(256) NOT NULL, 
	rack VARCHAR(64), 
	cell VARCHAR(64), 
	status VARCHAR(16) NOT NULL, 
	status_reason TEXT, 
	version INTEGER NOT NULL, 
	origin VARCHAR(16) NOT NULL, 
	original BOOLEAN NOT NULL, 
	parent_id VARCHAR(36), 
	source_row INTEGER, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cut_remnant_external UNIQUE (dataset_id, remnant_id), 
	CONSTRAINT ck_cut_remnant_dims CHECK (length_mm > 0 AND width_mm > 0), 
	CONSTRAINT ck_cut_remnant_age CHECK (age_days IS NULL OR age_days >= 0), 
	CONSTRAINT ck_cut_remnant_status CHECK (status in ('available','reserved','consumed','withdrawn')), 
	CONSTRAINT ck_cut_remnant_origin CHECK (origin in ('source','working','child')), 
	CONSTRAINT ck_cut_remnant_version CHECK (version >= 0), 
	FOREIGN KEY(dataset_id) REFERENCES cut_datasets (dataset_id), 
	FOREIGN KEY(parent_id) REFERENCES cut_remnants (id)
);

CREATE INDEX ix_cut_remnant_material_status ON cut_remnants (dataset_id, material_id, status);

CREATE INDEX ix_cut_remnants_dataset_id ON cut_remnants (dataset_id);

CREATE TABLE cut_placements (
	plan_row_id VARCHAR(36) NOT NULL, 
	part_id VARCHAR(128) NOT NULL, 
	remnant_id VARCHAR(128) NOT NULL, 
	x_mm INTEGER, 
	y_mm INTEGER, 
	rot INTEGER, 
	lock_kind VARCHAR(16) NOT NULL, 
	seq INTEGER NOT NULL, 
	PRIMARY KEY (plan_row_id, part_id), 
	CONSTRAINT ck_cut_placement_rot CHECK (rot IS NULL OR rot in (0,1)), 
	CONSTRAINT ck_cut_placement_lock CHECK (lock_kind in ('none','assignment','placement')), 
	FOREIGN KEY(plan_row_id) REFERENCES cut_plans (id) ON DELETE CASCADE
);

CREATE TABLE cut_reservations (
	id VARCHAR(36) NOT NULL, 
	dataset_id VARCHAR(128) NOT NULL, 
	remnant_row_id VARCHAR(36) NOT NULL, 
	plan_row_id VARCHAR(36), 
	plan_id VARCHAR(64) NOT NULL, 
	plan_revision INTEGER NOT NULL, 
	owner_context VARCHAR(256) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	version INTEGER NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	released_at VARCHAR(40), 
	consumed_at VARCHAR(40), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_cut_reservation_status CHECK (status in ('active','released','consumed')), 
	FOREIGN KEY(dataset_id) REFERENCES cut_datasets (dataset_id), 
	FOREIGN KEY(remnant_row_id) REFERENCES cut_remnants (id), 
	FOREIGN KEY(plan_row_id) REFERENCES cut_plans (id)
);

CREATE INDEX ix_cut_reservations_dataset_id ON cut_reservations (dataset_id);

CREATE UNIQUE INDEX uq_cut_reservation_active ON cut_reservations (remnant_row_id) WHERE status = 'active';
