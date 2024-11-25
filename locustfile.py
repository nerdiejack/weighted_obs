from locust import HttpUser, task, between

class AppUser(HttpUser):
    wait_time = between(1, 2)

    @task(85)
    def load_home_app(self):
        self.client.get("http://flask-app:5000/")

    @task(3)
    def load_error_app(self):
        self.client.get("http://flask-app:5000/error")

    @task(1)
    def load_db_test_app(self):
        self.client.get("http://flask-app:5000/db-test")

    @task(11)
    def load_heavy_app(self):
        self.client.get("http://flask-app:5000/heavy")

    @task(97)
    def load_app2(self):
        self.client.get("http://app2:5000/process")

    @task(3)
    def load_error_app2(self):
        self.client.get("http://app2:5000/error")

    @task(89)
    def load_app3(self):
        self.client.get("http://app3:5000/process")

    @task(11)
    def load_error_app3(self):
        self.client.get("http://app3:5000/error")

    @task(30)
    def load_app4(self):
        self.client.get("http://app4:5000/process")

    @task(70)
    def load_error_app4(self):
        self.client.get("http://app4:5000/error")