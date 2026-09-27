FROM public.ecr.aws/docker/library/maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn -B -DskipTests package

FROM mcr.microsoft.com/openjdk/jdk:17-ubuntu
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 10001 sandbox && useradd -u 10001 -g sandbox -d /workspace sandbox && mkdir -p /workspace && chown 10001:10001 /workspace
COPY --from=build /app/target/agent-sandbox-runtime-0.1.0.jar /opt/sandbox/runtime.jar
USER 10001:10001
WORKDIR /workspace
EXPOSE 8888
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=60", "-jar", "/opt/sandbox/runtime.jar"]
