# Databricks notebook source
# MAGIC %md
# MAGIC 
# MAGIC # AP Juice Lakehouse Platform

# COMMAND ----------

# MAGIC %md
# MAGIC ### Admin database setup
# MAGIC 
# MAGIC Running this notebook will set up a shared database **ap_juice_db_shared** to be used for AP Juice SQL Lab and grant access to the database to all users.
# MAGIC 
# MAGIC Users will need to be granted access to this database.

# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC ### Environment Setup
# MAGIC 
# MAGIC We will be using [Databricks Notebooks workflow](https://docs.databricks.com/notebooks/notebook-workflows.html) element to set up environment for this exercise. 
# MAGIC 
# MAGIC `dbutils.notebook.run()` command will run another notebook and return its output to be used here.
# MAGIC 
# MAGIC `dbutils` has some other interesting uses such as interacting with file system (check our `dbutils.fs.rm()` being used in the next cell) or to read Secrets.

# COMMAND ----------

setup_responses = dbutils.notebook.run("./Utils/Setup-Batch-Shared-Database", 0).split()

local_data_path = setup_responses[0]
dbfs_data_path = setup_responses[1]
database_name = setup_responses[2]

bronze_table_path = f"{dbfs_data_path}tables/bronze/"
silver_table_path = f"{dbfs_data_path}tables/silver/"
gold_table_path = f"{dbfs_data_path}tables/gold/"

autoloader_ingest_path = f"{dbfs_data_path}/autoloader_ingest/"

# Remove all files from location in case there were any
dbutils.fs.rm(bronze_table_path, recurse=True)
dbutils.fs.rm(silver_table_path, recurse=True)
dbutils.fs.rm(gold_table_path, recurse=True)

print("Local data path is {}".format(local_data_path))
print("DBFS path is {}".format(dbfs_data_path))
print("Database name is {}".format(database_name))

print("Brone Table Location is {}".format(bronze_table_path))
print("Silver Table Location is {}".format(silver_table_path))
print("Gold Table Location is {}".format(gold_table_path))

spark.sql(f"USE {database_name};")

# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC We can also run another notebook via magic `%run` command.  When we use `%run`, the called notebook is immediately executed and the functions and variables defined in it become available in the calling notebook. On the other hand, the `dbutils.notebook.run()` used above starts a new job to run the notebook.
# MAGIC 
# MAGIC In this case we will use separate notebook to define few functions.

# COMMAND ----------

#%run ../Utils/Define-Functions
username = database_name

base_table_path = f"dbfs:/FileStore/{username}/deltademoasset/"
local_data_path = f"/dbfs/FileStore/{username}/deltademoasset/"

spark.sql(f"CREATE DATABASE IF NOT EXISTS {database_name}_aux")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {database_name}_aux.jan_sales
USING DELTA
PARTITIONED BY (location)
AS 
SELECT *, from_unixtime(ts, "yyyy-MM-dd") as ts_date 
FROM json.`{base_table_path}sales_202201.json`
ORDER BY from_unixtime(ts, "yyyy-MM-dd")
""")

def get_incremental_data(ingest_path, location, date):
    df = spark.sql(f"""
  select CustomerID, Location, OrderSource, PaymentMethod, STATE, SaleID, SaleItems, ts, unix_timestamp() as exported_ts from {database_name}_aux.jan_sales
where location = '{location}' and ts_date = '{date}'
  """)
    df \
    .coalesce(1) \
    .write \
    .mode('overwrite') \
    .json(f"{ingest_path}{location}/{date}/daily_sales.json")
 
  
def get_fixed_records_data(ingest_path, location, date):
  df = spark.sql(f"""
  select CustomerID, Location, OrderSource, PaymentMethod, 'CANCELED' as STATE, SaleID, SaleItems, from_unixtime(ts) as ts, unix_timestamp() as exported_ts from {database_name}_aux.jan_sales
where location = '{location}' and ts_date = '{date}'
and state = 'PENDING'
  """)
  df \
  .coalesce(1) \
  .write \
  .mode('overwrite') \
  .json(f"{ingest_path}{location}/{date}/updated_daily_sales.json")

# COMMAND ----------

# MAGIC %md
# MAGIC ## ![ ](https://pages.databricks.com/rs/094-YMS-629/images/delta-lake-tiny-logo.png) Delta Architecture

# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC We already have seen store locations dataset. Let's redo the work this time using suggested Delta Architecture steps

# COMMAND ----------

# MAGIC %md
# MAGIC #### Load Bronze tables

# COMMAND ----------

data_file_location = f"{dbfs_data_path}/stores.csv"

bronze_table_name = "bronze_store_locations"
silver_table_name = "silver_store_locations"

df = spark.read\
  .option("header", "true")\
  .option("delimiter", ",")\
  .option("inferSchema", "true")\
  .csv(data_file_location)

spark.sql(f"DROP TABLE IF EXISTS {bronze_table_name};")

df.write \
  .mode("overwrite") \
  .option("path", f"{bronze_table_path}/{bronze_table_name}") \
  .saveAsTable(bronze_table_name)

silver_df = spark.sql(f"""
select *, 
case when id in ('SYD01', 'MEL01', 'BNE02', 'MEL02', 'PER01', 'CBR01') then 'AUS' when id in ('AKL01', 'AKL02', 'WLG01') then 'NZL' end as country_code
from {bronze_table_name}
""")

spark.sql(f"DROP TABLE IF EXISTS {silver_table_name};")


silver_df.write \
  .mode("overwrite") \
  .option("path", f"{silver_table_path}/{silver_table_name}") \
  .saveAsTable(silver_table_name)


# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC We have 2 more dimension tables that can be added to the Lakehouse without many data changes - dim_customers and dim_products.

# COMMAND ----------

data_file_location = f"{dbfs_data_path}/users.csv"

bronze_table_name = "bronze_customers"
silver_table_name = "silver_customers"

df = spark.read\
  .option("header", "true")\
  .option("delimiter", ",")\
  .option("inferSchema", "true")\
  .csv(data_file_location)

spark.sql(f"DROP TABLE IF EXISTS {bronze_table_name};")

df.write \
  .mode("overwrite") \
  .option("path", f"{bronze_table_path}/{bronze_table_name}") \
  .saveAsTable(bronze_table_name)

silver_df = spark.sql(f"""
SELECT store_id || "-" || cast(id as string) as unique_id, id, store_id, name, email FROM {bronze_table_name}
""")

spark.sql(f"DROP TABLE IF EXISTS {silver_table_name};")


silver_df.write \
  .mode("overwrite") \
  .option("path", f"{silver_table_path}/{silver_table_name}") \
  .saveAsTable(silver_table_name)


# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC And repeat for dim_products - note that this time our input file is json and not csv

# COMMAND ----------

data_file_location = f"{dbfs_data_path}/products.json"

bronze_table_name = "bronze_products"
silver_table_name = "silver_products"

df = spark.read\
  .json(data_file_location)

spark.sql(f"DROP TABLE IF EXISTS {bronze_table_name};")

df.write \
  .mode("overwrite") \
  .option("path", f"{bronze_table_path}/{bronze_table_name}") \
  .saveAsTable(bronze_table_name)

silver_df = spark.sql(f"""
select * from {bronze_table_name}
""")

spark.sql(f"DROP TABLE IF EXISTS {silver_table_name};")


silver_df.write \
  .mode("overwrite") \
  .option("path", f"{silver_table_path}/{silver_table_name}") \
  .saveAsTable(silver_table_name)


# COMMAND ----------

import pyspark.sql.functions as F

checkpoint_path = f'{local_data_path}/_checkpoints'
schema_path = f'{local_data_path}/_schema'
write_path = f'{bronze_table_path}/bronze_sales'

spark.sql("drop table if exists bronze_sales")

refresh_autoloader_datasets = True

if refresh_autoloader_datasets:
  # Run these only if you want to start a fresh run!
  dbutils.fs.rm(checkpoint_path,True)
  dbutils.fs.rm(schema_path,True)
  dbutils.fs.rm(write_path,True)
  dbutils.fs.rm(autoloader_ingest_path, True)
  
  dbutils.fs.mkdirs(autoloader_ingest_path)
  
  dbutils.fs.cp(f"{dbfs_data_path}/sales_202110.json", autoloader_ingest_path)
  dbutils.fs.cp(f"{dbfs_data_path}/sales_202111.json", autoloader_ingest_path)
  dbutils.fs.cp(f"{dbfs_data_path}/sales_202112.json", autoloader_ingest_path)

get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-01')
get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-02')
get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-03')
get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-04')
get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-05')
get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-06')
get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-07')

# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC If we have new data files arriving - rerunning autoloader cell will only process those yet unseen files. 
# MAGIC You can try it out by running `get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-01')` and then re-running autoloader cell.

# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC You can schedule autoloder to run on required schedule (e.g. every night) and it will always process files uploaded since last run.
# MAGIC 
# MAGIC What if we would like to process files as soon as they are uploaded? Autoloader can run in **streaming mode** with one simple change in the code used - removing Trigger Once option.
# MAGIC 
# MAGIC Start the autoloader running cell bellow, wait for stream to start and generate new upload file by running `get_incremental_data(autoloader_ingest_path, 'SYD01','2022-01-02')`. You can see new files being processed as they are uploaded.

# COMMAND ----------

# Set up the stream to begin reading incoming files from the autoloader_ingest_path location.
df = spark.read \
  .option("recursiveFileLookup","true") \
  .json(autoloader_ingest_path) \
  .withColumn("file_path",F.input_file_name()) \
  .withColumn("inserted_at", F.current_timestamp()) 


df.write \
  .mode("overwrite") \
  .option("mergeSchema", "true") \
  .option("path",write_path) \
  .saveAsTable('bronze_sales')

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Run this to see newly processed rows
# MAGIC select file_path, count(*) number_of_records
# MAGIC from bronze_sales
# MAGIC group by file_path

# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC ### Silver Tables
# MAGIC 
# MAGIC Now that we have a bronze table ready - let's a create silver one! 
# MAGIC 
# MAGIC We can start by using same approach as for the dimension tables earlier - clean and de-duplicate data from bronze table, rename columns to be more business friendly and save it as silver table.

# COMMAND ----------

# MAGIC %sql 
# MAGIC 
# MAGIC create or replace view v_silver_sales 
# MAGIC as 
# MAGIC with with_latest_record_id as (
# MAGIC   select
# MAGIC     *,
# MAGIC     row_number() over (
# MAGIC       partition by SaleID
# MAGIC       order by
# MAGIC         coalesce(exported_ts, 0) desc
# MAGIC     ) as latest_record
# MAGIC   from
# MAGIC     bronze_sales
# MAGIC ),
# MAGIC newest_records as (
# MAGIC   select
# MAGIC     saleID as id,
# MAGIC     from_unixtime(ts) as ts,
# MAGIC     Location as store_id,
# MAGIC     CustomerID as customer_id,
# MAGIC     location || "-" || cast(CustomerID as string) as unique_customer_id,
# MAGIC     OrderSource as order_source,
# MAGIC     STATE as order_state,
# MAGIC     SaleItems as sale_items
# MAGIC   from
# MAGIC     with_latest_record_id
# MAGIC   where
# MAGIC     latest_record = 1
# MAGIC )
# MAGIC select
# MAGIC   *,
# MAGIC   sha2(concat_ws(*, '||'), 256) as row_hash -- add a hash of all values to easily pick up changed rows
# MAGIC from
# MAGIC   newest_records

# COMMAND ----------

spark.sql("drop table if exists silver_sales;")

spark.sql(f"""
create table silver_sales 
using delta
location '{silver_table_path}silver_sales'
as
select * from v_silver_sales;
""")

# COMMAND ----------

# MAGIC %md
# MAGIC 
# MAGIC Sales table is nice, but we also have sales items information object that can be split into rows for easier querying

# COMMAND ----------

# MAGIC %sql 
# MAGIC create or replace view v_silver_sale_items 
# MAGIC as 
# MAGIC 
# MAGIC with itemised_records as (
# MAGIC   select
# MAGIC     *,
# MAGIC     posexplode(
# MAGIC       from_json(
# MAGIC         sale_items,
# MAGIC         'array<struct<id:string,size:string,notes:string,cost:double,ingredients:array<string>>>'
# MAGIC       )
# MAGIC     )
# MAGIC   from
# MAGIC     v_silver_sales
# MAGIC ),
# MAGIC all_records as (
# MAGIC   select
# MAGIC     id || "-" || cast(pos as string) as id,
# MAGIC     id as sale_id,
# MAGIC     store_id,
# MAGIC     pos as item_number,
# MAGIC     col.id as product_id,
# MAGIC     col.size as product_size,
# MAGIC     col.notes as product_notes,
# MAGIC     col.cost as product_cost,
# MAGIC     col.ingredients as product_ingredients
# MAGIC   from
# MAGIC     itemised_records
# MAGIC )
# MAGIC select
# MAGIC   *,
# MAGIC   sha2(concat_ws(*, '||'), 256) as row_hash
# MAGIC from
# MAGIC   all_records

# COMMAND ----------

spark.sql("drop table if exists silver_sale_items");

spark.sql(f"""
create table silver_sale_items
using delta
location '{silver_table_path}silver_sale_items'
as
select * from v_silver_sale_items;
""")

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE dim_customers
# MAGIC as select row_number() over (ORDER BY unique_id) as customer_skey , unique_id, store_id, name, email,'Y' as current_record,cast('1900-01-01 00:00:00'as timestamp) as start_date, cast(null as timestamp) as end_date
# MAGIC from silver_customers

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE dim_products
# MAGIC as select row_number() over (ORDER BY id) as product_skey , id, ingredients, name,'Y' as current_record,cast('1900-01-01 00:00:00'as timestamp) as start_date, cast(null as timestamp) as end_date
# MAGIC from silver_products

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE dim_store_locations
# MAGIC as select row_number() over (ORDER BY id) as slocation_skey, id, name, city, hq_address, country_code, phone_number, 'Y' as current_record,cast('1900-01-01 00:00:00'as timestamp) as start_date, cast(null as timestamp) as end_date
# MAGIC from silver_store_locations

# COMMAND ----------

# MAGIC %sql
# MAGIC Create or replace table apj_sales_fact
# MAGIC With apj_sales_fact_tmp as (Select f.id as sale_id, f.ts, f.order_source, f.order_state, f.unique_customer_id, f.store_id
# MAGIC from  silver_sales f
# MAGIC )
# MAGIC 
# MAGIC Select dc.customer_skey as customer_skey, dsl.slocation_skey as slocation_skey, f.* from apj_sales_fact_tmp f
# MAGIC 
# MAGIC /* Get the Customer SKEY record */
# MAGIC 
# MAGIC join dim_customers dc
# MAGIC on f.unique_customer_id = dc.unique_id
# MAGIC 
# MAGIC /* Get the Location SKEY record */
# MAGIC join dim_store_locations dsl 
# MAGIC on f.store_id = dsl.id

# COMMAND ----------

# MAGIC %sql
# MAGIC Create or replace table apj_sale_items_fact
# MAGIC With apj_sale_items_fact_tmp as (Select f.sale_id, f.product_id, f.store_id, f.product_size, f.product_cost, f.product_ingredients
# MAGIC from  silver_sale_items f
# MAGIC )
# MAGIC 
# MAGIC Select dp.product_skey as product_skey, dsl.slocation_skey as slocation_skey, ss.unique_customer_id,  f.* from apj_sale_items_fact_tmp f
# MAGIC 
# MAGIC /* Get the Product SKEY record */
# MAGIC 
# MAGIC join dim_products dp
# MAGIC on f.product_id = dp.id
# MAGIC 
# MAGIC /* Get the Location SKEY record */
# MAGIC join dim_store_locations dsl 
# MAGIC on f.store_id = dsl.id
# MAGIC 
# MAGIC join silver_sales ss
# MAGIC on f.sale_id = ss.id

# COMMAND ----------

print(f"grant usage on schema {database_name} to users;");
print(f"grant select on schema {database_name} to users;");
