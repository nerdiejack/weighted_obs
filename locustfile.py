from locust import HttpUser, task, between

class FlaskUser(HttpUser):
    wait_time = between(1, 2)

    @task(25)
    def load_home(self):
        self.client.get("/")

    @task(1)
    def load_error(self):
        self.client.get("/error")

    @task(3)
    def load_db_test(self):
        self.client.get("/db-test")

    @task(5)
    def load_heavy(self):
        self.client.get("/heavy")
