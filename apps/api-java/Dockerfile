ARG MAVEN_IMAGE=public.ecr.aws/docker/library/maven:3.9-eclipse-temurin-21
ARG RUNTIME_IMAGE=mcr.microsoft.com/openjdk/jdk:17-ubuntu
FROM ${MAVEN_IMAGE} AS build
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn -B -DskipTests package

FROM ${RUNTIME_IMAGE}
WORKDIR /app
COPY --from=build /app/target/gameweare-api-0.1.0-SNAPSHOT.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70", "-jar", "/app/app.jar"]
