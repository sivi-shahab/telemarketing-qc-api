# Allure CLI berbasis Java, dan host tidak punya JRE — jadi report dirender di sini.
FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g allure-commandline@2.43.0
WORKDIR /work
