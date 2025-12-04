FROM python:3.12
WORKDIR /app
COPY docker/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY . .
