#!/bin/bash
DB_NAME="pgbench_db"
SCALE=10
DURATION=10

until pg_isready -h postgres -U user -p 5432; do
    echo "Waiting for database to be ready..."
    sleep 2
done

# Check if the pgbench tables are initialized
TABLE_EXISTS=$(PGPASSWORD='password' psql -U user -h postgres -d $DB_NAME -c "\dt pgbench_branches" | grep -q "pgbench_branches"; echo $?)

if [ "$TABLE_EXISTS" -ne 0 ]; then
    echo "Initializing pgbench tables in database $DB_NAME..."
    PGPASSWORD='password' pgbench -i -s $SCALE -U user -h postgres -d $DB_NAME
fi

TEMP_FILE="/pgbench_results/pgbench_temp_result.txt"
FINAL_FILE="/pgbench_results/pgbench_last_result.txt"

echo "Running pgbench on database $DB_NAME..."
PGPASSWORD='password' pgbench -T $DURATION -c $SCALE -U user -h postgres -d $DB_NAME > $TEMP_FILE 2>&1

if [ $? -eq 0 ]; then
    echo "pgbench run compelte at $(date). Moving results to $FINAL_FILE" >> /pgbench_results/pgbench_debug_log.txt
    mv $TEMP_FILE $FINAL_FILE
else
    echo "pgbench encountered an error at $(date)." >> /pgbench_results/pgbench_debug_log.txt
fi