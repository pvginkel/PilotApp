// Tests PilotApp's backend and frontend in a Kubernetes Job, then builds the pilot and pilot-ui
// images and pins them into PilotDeploy, which Argo CD syncs to prd.
//
// The images are built from the tree the suite passed on, so `latest` is tagged at build time and
// there is no promote stage.
//
// Controller config:
//   - Job: PilotApp
//   - SCM: pvginkel/PilotApp, branch main
//   - Script Path: Jenkinsfile

library identifier: 'JenkinsPipelineUtils', changelog: false

pipeline {
    agent {
        kubernetes {
            inheritFrom 'jenkins-agent kaniko'
            yamlMergeStrategy merge()
            yaml podYaml(templates: ['k8s'])
        }
    }

    options {
        disableConcurrentBuilds(abortPrevious: true)
        skipDefaultCheckout()
        timeout(time: 60, unit: 'MINUTES')
        timestamps()
    }

    triggers {
        githubPush()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Test') {
            steps {
                script {
                    modernApp.test(
                        job: 'pilot-validation',
                        install: 'uv sync --locked --no-dev',
                        run: 'uv run --no-sync',
                        suites: ['backend', 'frontend'],
                        services: [],
                        env: [:],
                        secrets: [],
                    )
                }
            }
        }

        stage('Build pilot image') {
            steps {
                container('kaniko') {
                    script {
                        helmCharts.kaniko2(
                            dockerfile: 'backend/Dockerfile',
                            context: 'backend',
                            destinations: [
                                "registry:5000/pilot:${currentBuild.number}",
                                'registry:5000/pilot:latest',
                            ]
                        )
                    }
                }
            }
        }

        stage('Build pilot-ui image') {
            steps {
                // The frontend shows the commit it was built from, and its build context holds no
                // .git to read it from.
                sh 'git rev-parse HEAD > frontend/git-rev'
                container('kaniko') {
                    script {
                        helmCharts.kaniko2(
                            dockerfile: 'frontend/Dockerfile',
                            context: 'frontend',
                            destinations: [
                                "registry:5000/pilot-ui:${currentBuild.number}",
                                'registry:5000/pilot-ui:latest',
                            ]
                        )
                    }
                }
            }
        }

        stage('Write image pins') {
            steps {
                container('k8s') {
                    script {
                        cicd.writeVersionPins(repo: 'pvginkel/PilotDeploy', pins: [
                            'config/prd/values.yaml': [
                                'images.pilot': ":${currentBuild.number}",
                                'images.pilotUI': ":${currentBuild.number}",
                            ],
                        ])
                    }
                }
            }
        }
    }
}
