## Environment set up

1. Clone the repository:

```bash
git clone <repository-url>
cd home
```

2. Install [mise](https://mise.jdx.dev/)

&nbsp; &nbsp; &nbsp; &nbsp; a. Make sure you've configured it to [work with IDEs](https://mise.jdx.dev/ide-integration.html#adding-shims-to-path-default-shell)

3. Install dependencies

```bash
mise install
mise setup
```

4. Install recommended VSCode extensions

That's it! Your environment is set up :)

### Run code quality checks:

```bash
# Format code
mise run format

# Check linting
mise run lint

# Type checking
mise run typecheck

# Run tests
mise run test
```

## CI

### RWX

CI runs on [RWX](https://www.rwx.com). Every pull request and CLI run executes
the checks defined in [.rwx/ci.yml](.rwx/ci.yml) (format, lint, typecheck,
test) plus a native OCI image build, and publishes an immutable image tag to
Fly's private registry. Merges to main additionally update the registry's
`latest` tag and deploy the image to Fly.
