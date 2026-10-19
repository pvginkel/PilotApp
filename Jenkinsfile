// Tests PilotApp's backend and frontend in a Kubernetes Job and its pilot-sync sidecar in the pod,
// then builds the pilot, pilot-ui and pilot-sync images and pins the first two into PilotDeploy,
// which Argo CD syncs to prd. pilot-sync, the store environment's sync sidecar, runs in no pod of
// PilotDeploy's.
//
// The images are built from the tree the suites passed on, so `latest` is tagged at build time and
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
            // golang runs the image this environment's `go` tool runs (.kubecoder/config.yaml), so a
            // failure of the sidecar's tests here is one there too.
            yaml podYaml(templates: ['k8s'], images: [
                [image: 'registry:5000/kube-coder-go-toolchain:latest', name: 'golang'],
            ])
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
                    // The services are containers in the Job's pod and start with the suite, so the
                    // suite runner waits for them (backend/scripts/wait-for-services.py).
                    // PostgreSQL is a sidecar so that both suites, pytest and Playwright, have a
                    // server to create and drop their databases on, at the default
                    // TEST_DATABASE_ADMIN_URL. Its major version is production's.
                    modernApp.test(
                        job: 'pilot-validation',
                        install: 'uv sync --locked --no-dev',
                        run: 'uv run --no-sync',
                        suites: ['backend', 'frontend'],
                        services: [
                            [name: 'postgres', image: 'postgres:18-trixie', env: [
                                POSTGRES_PASSWORD: 'postgres',
                            ]],
                        ],
                        env: [
                            // CI is the tst tier; under testing STAGE would default to local-tst.
                            STAGE: 'tst',
                            // The library fixes run-suite's flags, so the suite runner's pnpm store
                            // cache is switched on here instead of with --build-cache.
                            BUILD_CACHE: 'true',
                        ],
                        secrets: [],
                    )
                }
            }
        }

        // The sidecar's tests are no suite of the validation Job, whose image has no Go.
        stage('Test sidecar') {
            steps {
                container('golang') {
                    dir('sidecar') {
                        sh 'go vet ./...'
                        sh 'go test -race ./...'
                    }
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

        stage('Build pilot-sync image') {
            steps {
                container('kaniko') {
                    script {
                        helmCharts.kaniko2(
                            dockerfile: 'sidecar/Dockerfile',
                            context: 'sidecar',
                            destinations: [
                                "registry:5000/pilot-sync:${currentBuild.number}",
                                'registry:5000/pilot-sync:latest',
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
