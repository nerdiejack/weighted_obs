FROM postgres:13
ENV PGUSER=user
ENV PGPASSWORD=password
ENV PGHOST=postgres

RUN apt-get update && apt-get install -y cron

COPY run_pgbench.sh /run_pgbench.sh
COPY crontab.txt /etc/cron.d/pgbench-cron

RUN chmod +x /etc/cron.d/pgbench-cron

RUN chmod +x /run_pgbench.sh

RUN crontab /etc/cron.d/pgbench-cron

RUN mkdir /pgbench_results

CMD ["cron", "-f"]
