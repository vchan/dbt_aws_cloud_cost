# dbt + BigQuery + Lake Compute demo (AWS cloud cost)

A dbt project that runs on BigQuery and uses Fivetran's **Lake Compute** (a
`type: lakecompute` dbt Fusion adapter, running DuckDB) for one model, using
dbt Fusion's multi-adapter profile targets.

The source data is a mocked version of AWS's Cost & Usage Report pipeline.
The models are adapted from Fivetran's
[`dbt_aws_cloud_cost`](https://github.com/fivetran/dbt_aws_cloud_cost) package.

> Throughout, "dbt" means the dbt Fusion (dbt Core v2) `dbt` CLI. Lake Compute
> support for BigQuery needs a Fusion build that has it, see
> [Install dbt](#install-dbt).

## How it works

A single profile target (`prod`) declares two adapter connections: `bigquery`
(the default) and `lakecompute`. Models opt into Lake Compute with
`adapter: lakecompute`; everything else runs on BigQuery.

```
aws_cost_report (seed, BigQuery)
  -> stg_report (BigQuery Iceberg table, catalog bigquery_iceberg)
      -> daily_overview (adapter=lakecompute)    [reads stg_report, runs DuckDB SQL, publishes to BigQuery]
          -> daily_instance_report, daily_product_report (BigQuery)
```

- `stg_report` is a native BigQuery model written as a BigQuery-managed
  Iceberg table (`catalog_name: bigquery_iceberg`, a `biglake_metastore`
  catalog in `catalogs.yml`). Lake Compute reads BigQuery Iceberg tables
  through BigQuery's Iceberg REST catalog, so this is what lets
  `daily_overview` read it.
- `daily_overview` is the only Lake Compute model. It is a `table`, written in
  DuckDB SQL. Lake Compute stores the result as an Iceberg table and publishes
  it to BigQuery, where the two report models `ref` it like any native table.
  It has `unique` and `not_null` data tests on `unique_key`.
- The seed and the two report models are plain BigQuery.

## Configuration to change for your environment

`profiles.yml` and `catalogs.yml` hold the operator's test values. Change:

| Setting | Where | Value in this repo |
| --- | --- | --- |
| BigQuery project | `profiles.yml` (`project`, and `database` on the lakecompute output), `catalogs.yml` (`connection_id`) | `singular-vector-135519` |
| BigQuery dataset | `profiles.yml` `dataset` and `+schema` in `dbt_project.yml` (see `macros/generate_schema_name.sql`) | `aws_cloud_cost` |
| BigQuery location | `profiles.yml` | `us-east4` |
| BigQuery connection | `profiles.yml` `bigquery_connection`, `catalogs.yml` `connection_id` | `singular-vector-135519.us-east4.quack_probe_conn` |
| Iceberg storage | `catalogs.yml` `external_volume` | `gs://lake_compute_bq_demo/aws_cloud_cost` |
| Lake Compute API | `profiles.yml` `base_url` | `http://localhost:8080` |

`bigquery_connection` is a field of the `lakecompute` output that tells Lake
Compute which BigQuery connection to publish through. A Fusion build that
doesn't know the field fails on the profile.

## Quick start

### Prerequisites

- macOS or Linux
- A dbt Fusion build with BigQuery support for Lake Compute (see below)
- Google Application Default Credentials for BigQuery (`method: oauth`):
  `gcloud auth application-default login`
- A Lake Compute API reachable at `base_url`, and a bearer token for it
- The BigQuery connection must be allowed to write to the Cloud Storage bucket
  in `catalogs.yml`

### Steps

1. Install or build `dbt` ([Install dbt](#install-dbt)).
2. Write `.env`:
   ```bash
   scripts/setup.sh
   ```
3. Add `LAKE_COMPUTE_AUTH_TOKEN` to `.env` (see `.env.example`), then load it:
   ```bash
   set -a && source .env && set +a        # or: direnv allow
   ```
4. Run:
   ```bash
   dbt deps
   dbt seed
   dbt build
   ```

`DBT_ENGINE_EXPERIMENTAL_MULTI_ADAPTER=true` must be set: selecting a node's
adapter is still experimental in Fusion. `.env.example` has it.

`dbt seed` and `dbt run --select stg_report` need only BigQuery credentials,
not Lake Compute. The seed has 10,000 rows. Loading it through the ADBC
BigQuery driver is slow (minutes); that is the driver's seed path, not the
project.

### Running against a local driver build

A Fusion debug build can load a locally built Lake Compute driver. Put the
driver and the BigQuery driver in one directory (the BigQuery driver is in
`~/Library/Caches/com.getdbt/adbc/<target>/` once Fusion has downloaded it)
and point Fusion at it:

```bash
mkdir -p /tmp/dbt-drivers
ln -sf /path/to/quack/target/release/libadbc_driver_dbt.dylib /tmp/dbt-drivers/
ln -sf "$HOME/Library/Caches/com.getdbt/adbc/aarch64-apple-darwin/libadbc_driver_bigquery-<version>.dylib" \
  /tmp/dbt-drivers/libadbc_driver_bigquery.dylib

export ADBC_REPOSITORY=/tmp/dbt-drivers
export DISABLE_CDN_DRIVER_CACHE=true
export DISABLE_AUTO_DRIVER_REBUILD=true
```

## Comparing with a BigQuery-native build

`daily_overview` is DuckDB SQL that is also valid BigQuery SQL: it avoids
dialect-specific functions, and its numeric columns are 38 digits with 9
decimals on both engines (`decimal(38, 9)` in DuckDB, BigQuery's `NUMERIC` in
the reference build). The var `aws_cloud_cost_reference` runs the same
model on BigQuery instead of Lake Compute. Build the reference into a separate
dataset with `AWS_CLOUD_COST_TARGET_SCHEMA`:

```bash
AWS_CLOUD_COST_TARGET_SCHEMA=aws_cloud_cost_reference \
  dbt build --vars '{aws_cloud_cost_reference: true}'
```

This reloads the seed and `stg_report` into the reference dataset and builds
all three models natively there. It does not call Lake Compute, and it also
parses with Fusion builds that can't yet read a BigQuery Iceberg upstream from
a `lakecompute` model. Then compare each of `daily_overview`,
`daily_instance_report`, and `daily_product_report` as multisets, grouping
complete rows with their counts and using `EXCEPT DISTINCT` in both
directions:

```sql
with a as (select to_json_string(t) as r, count(*) as n from `PROJECT.aws_cloud_cost.daily_overview` t group by 1),
     b as (select to_json_string(t) as r, count(*) as n from `PROJECT.aws_cloud_cost_reference.daily_overview` t group by 1)
select
  (select count(*) from (select * from a except distinct select * from b)) as only_in_lake_compute,
  (select count(*) from (select * from b except distinct select * from a)) as only_in_reference
```

Both counts should be 0.

## Porting notes (Snowflake to BigQuery)

- `try_cast` became `dbt.safe_cast`; timestamps use `dbt.type_timestamp()`.
- `aws_cloud_cost_regex_group` uses BigQuery's `regexp_extract(value, pattern)`
  (it returns the first capture group and takes no group index).
- `daily_overview` aliases are lowercase and unquoted. The uppercase quoted
  aliases only worked around Snowflake's identifier casing.
- The seed columns are all `string`; `stg_report` casts them to typed columns.
- Removed: the `SEEDS` database override, `create_seed_db` and
  `set_rsa_public_key` macros, and the Snowflake and Horizon helper scripts.

## Install dbt

This needs a dbt Fusion build with BigQuery support for Lake Compute. Until
it is released, build it from the `fs` repo (a branch with BigQuery support
for `adapter: lakecompute`):

```bash
cd /path/to/fs
cargo build --bin dbt    # produces target/debug/dbt
target/debug/dbt --version
```

Fusion builds that don't have this support can still seed and build the native
models, using `--vars '{aws_cloud_cost_reference: true}'` (see above).

## Regenerating the seed

The seed is committed (`seeds/aws_cost_report.csv`), so you normally never
touch it. The generator that originally produced it has been removed from this
repo.

## Troubleshooting

- **`Selecting a node's adapter with adapter: lakecompute is experimental`**:
  set `DBT_ENGINE_EXPERIMENTAL_MULTI_ADAPTER=true`.
- **`upstream ... is not reachable through a catalog`** at parse: this Fusion
  build can't yet read a `biglake_metastore` upstream from a Lake Compute
  model. Use a build with BigQuery support, or the reference var above.
- **`Driver not found: adbc_driver_bigquery`**: `ADBC_REPOSITORY` points at a
  directory that lacks the BigQuery driver, see
  [Running against a local driver build](#running-against-a-local-driver-build).
- **`UnusedConfigKey`: `threads:` on the `lakecompute` connection**: thread
  count is target-wide (taken from the default connection or `--threads`);
  don't set `threads:` on a non-default adapter entry.
