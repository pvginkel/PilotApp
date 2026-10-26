// Tests PilotApp's backend and frontend in a Kubernetes Job and its pilot-sync sidecar in the pod,
// then builds the pilot, pilot-ui and pilot-sync images, each tagged dev-<n> and dev-latest, and
// pins the first two into PilotDeploy's main, which Argo CD syncs to pilot-dev. The prd pins it
// writes there take effect when PilotApp/Promote-PRD retags the three images prd-<n> and advances
// prd. pilot-sync, the store environment's sync sidecar, runs in no pod of PilotDeploy's.
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
                // The frontend shows the commit it was built from, and its build context holds no
                // .git to read it from.
                sh 'git rev-parse HEAD > frontend/git-rev'
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
                            ],
                            'config/prd/values.yaml': [
                                'images.pilot': ":prd-${n}",
                                'images.pilotUI': ":prd-${n}",
                            ],
                        ])
                    }
                }
            }
        }
    }
}
