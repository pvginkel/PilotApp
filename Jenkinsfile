// Tests PilotApp's backend and frontend in a Kubernetes Job and its pilot-sync sidecar and its
// collector in the pod, then builds the pilot, pilot-ui, pilot-sync and pilot-collector images, each
// tagged dev-<n> and dev-latest, and pins pilot, pilot-ui and pilot-collector into PilotDeploy's
// main, which Argo CD syncs to pilot-dev. The prd pins it writes there take effect when
// PilotApp/Promote-PRD retags the four images prd-<n> and advances prd. pilot-sync, the store
// environment's sync sidecar, runs in no pod of PilotDeploy's.
//
// Controller config:
//   - Job: PilotApp/Build-Main
//   - SCM: pvginkel/PilotApp, branch main
//   - Script Path: Jenkinsfile

library identifier: 'JenkinsPipelineUtils', changelog: false

pipeline {
    agent {
        kubernetes {
            inheritFrom 'jenkins-agent kaniko'
            yamlMergeStrategy merge()
            // golang runs the image this environment's `go` tool runs (.kubecoder/config.yaml), so a
            // failure of the sidecar's tests here is one there too. modern-app-toolchain, the
            // validation Job's image, runs the collector's.
            yaml podYaml(templates: ['k8s', 'modern-app-toolchain'], images: [
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
                // The frontend shows the commit it was built from, and neither the suite's tree
                // (modernApp.test leaves out .git) nor the image's build context holds .git to
                // read it from (vite-build-commit.ts).
                sh 'git rev-parse HEAD > frontend/git-rev'
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
                            // The suite as `kc project test` runs it: pytest on eight processes
                            // (pytest-xdist), Playwright on four workers, about 1.1 GiB apiece. The
                            // fixed flags again: pytest reads PYTEST_ADDOPTS itself, and run-suite
                            // reads PLAYWRIGHT_WORKERS for its --workers.
                            PYTEST_ADDOPTS: '-n 8',
                            PLAYWRIGHT_WORKERS: '4',
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

        // The collector's tests are no suite of the validation Job either: its run-suite runs the
        // backend's and the frontend's alone. They need no service. The walk's proof against
        // Pilot's routes is the backend suite's (backend/tests/collector).
        stage('Test collector') {
            steps {
                container('modern-app-toolchain') {
                    dir('collector') {
                        sh 'uv sync --locked'
                        sh 'uv run --no-sync pytest'
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
                                "registry:5000/pilot:dev-${currentBuild.number}",
                                'registry:5000/pilot:dev-latest',
                            ]
                        )
                    }
                }
            }
        }

        stage('Build pilot-ui image') {
            steps {
                // frontend/openapi-cache links to ../backend/openapi-cache, outside the build
                // context, where the link would dangle in the image.
                sh '''
                    test -f backend/openapi-cache/openapi.json
                    rm frontend/openapi-cache
                    cp -r backend/openapi-cache frontend/openapi-cache
                '''
                container('kaniko') {
                    script {
                        helmCharts.kaniko2(
                            dockerfile: 'frontend/Dockerfile',
                            context: 'frontend',
                            destinations: [
                                "registry:5000/pilot-ui:dev-${currentBuild.number}",
                                'registry:5000/pilot-ui:dev-latest',
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
                                "registry:5000/pilot-sync:dev-${currentBuild.number}",
                                'registry:5000/pilot-sync:dev-latest',
                            ]
                        )
                    }
                }
            }
        }

        // The context is the repository's root: the collector takes packages by path from
        // backend/packages, and the root's .dockerignore keeps the context to what the image
        // copies, so the environment the tests left in collector/ stays out.
        stage('Build pilot-collector image') {
            steps {
                container('kaniko') {
                    script {
                        helmCharts.kaniko2(
                            dockerfile: 'collector/Dockerfile',
                            context: '.',
                            destinations: [
                                "registry:5000/pilot-collector:dev-${currentBuild.number}",
                                'registry:5000/pilot-collector:dev-latest',
                            ]
                        )
                    }
                }
            }
        }

        // One commit on PilotDeploy's main pins both stages: Argo CD syncs pilot-dev from main, so
        // the commit rolls dev, and pilot-prd follows prd, which only PilotApp/Promote-PRD moves to a
        // commit of main, so the prd pins are written now for the promotion to release.
        stage('Write image pins') {
            steps {
                container('k8s') {
                    script {
                        String n = "${currentBuild.number}"
                        cicd.writeVersionPins(repo: 'pvginkel/PilotDeploy', pins: [
                            'config/dev/values.yaml': [
                                'images.pilot': ":dev-${n}",
                                'images.pilotUI': ":dev-${n}",
                                'images.collector': ":dev-${n}",
                            ],
                            'config/prd/values.yaml': [
                                'images.pilot': ":prd-${n}",
                                'images.pilotUI': ":prd-${n}",
                                'images.collector': ":prd-${n}",
                            ],
                        ])
                    }
                }
            }
        }
    }
}
