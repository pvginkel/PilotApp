import { execSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import type { Plugin } from 'vite'

// CI's trees, the suite's and the image's build context, hold no .git: the Jenkinsfile writes the
// commit here at checkout.
const GIT_REV = path.resolve(__dirname, 'git-rev')

/**
 * Embeds the commit the page is built from as `import.meta.env.VITE_BUILD_COMMIT`, which the
 * profile menu shows at its foot: from `git-rev` where it exists, else the work tree's HEAD as
 * the dev server or the build starts.
 */
export function buildCommit(): Plugin {
  return {
    name: 'build-commit',
    config() {
      const commit = fs.existsSync(GIT_REV)
        ? fs.readFileSync(GIT_REV, 'utf8').trim()
        : execSync('git rev-parse HEAD', { cwd: __dirname, encoding: 'utf8' }).trim()
      return { define: { 'import.meta.env.VITE_BUILD_COMMIT': JSON.stringify(commit) } }
    },
  }
}
