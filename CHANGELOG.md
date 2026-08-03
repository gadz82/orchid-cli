# CHANGELOG

<!-- version list -->

## v1.11.0 (2026-08-03)

### Features

- **cli**: Add `external-agents` command to manage CLI delegation tools
  ([`d8dcc0e`](https://github.com/gadz82/orchid-cli/commit/d8dcc0e347ea5db0d0cc22660614425e0d78f0e7))


## v1.10.2 (2026-07-29)

### Bug Fixes

- **cli**: Update project description
  ([`3ac8563`](https://github.com/gadz82/orchid-cli/commit/3ac85630672fdfc4d6a7438b07e0eb6f60fc13bc))


## v1.10.1 (2026-07-29)

### Bug Fixes

- Refine imports, type annotations, and exception handling
  ([`cf4b4fe`](https://github.com/gadz82/orchid-cli/commit/cf4b4fe0d44e15e825a7083cf67fa02720d417c6))

- Remove unused skill generation
  ([`f36cfec`](https://github.com/gadz82/orchid-cli/commit/f36cfecdb50b70a7f274565057c0aa330993584d))

- Simplify imports and add missing blank lines in tests
  ([`432ae86`](https://github.com/gadz82/orchid-cli/commit/432ae86fa888cdb875a58b0dc6197e27026f9a22))

- Update orchid-ai dependency to version 1.8.10
  ([`c102d0f`](https://github.com/gadz82/orchid-cli/commit/c102d0f5f4954d3e7dbb7db94ab33a1bd87ee442))

- Update orchid-ai dependency to version 1.8.10
  ([`8538b5b`](https://github.com/gadz82/orchid-cli/commit/8538b5bcfd9d1385a59b04a2062cab6ee251de27))

- **cli**: Bump orchid-cli version to 1.10.1 for patch release
  ([`eae9e26`](https://github.com/gadz82/orchid-cli/commit/eae9e2613b4fdb976154feb450ed6f09c85bf057))

- **cli**: Update project description
  ([`700f4d3`](https://github.com/gadz82/orchid-cli/commit/700f4d3aaa339e9a52349b2419204be15769e3a3))


## v1.10.0 (2026-06-05)

### Bug Fixes

- Update orchid-ai dependency to version 1.8.8
  ([`a6fee91`](https://github.com/gadz82/orchid-cli/commit/a6fee91bf12607b612492f0a27dd0b46d7e7bf56))

- **cli**: Streamline auth handling in chat_send and flower templates
  ([`e6e9076`](https://github.com/gadz82/orchid-cli/commit/e6e90767c30b6b7e5307b097513284bcb167f8aa))

### Features

- **cli**: Add `cli_rag` support for CLI-specific RAG configuration and tests
  ([`e5b6303`](https://github.com/gadz82/orchid-cli/commit/e5b6303a36dae5ac3b10b9a88c10df90c4e272cf))


## v1.9.2 (2026-06-01)

### Bug Fixes

- Update orchid-ai dependency to version 1.8.6 across all modules
  ([`1156fcb`](https://github.com/gadz82/orchid-cli/commit/1156fcb5d7eeb2b2e32b27c7373b8c5c1f5b29f4))


## v1.9.1 (2026-05-29)

### Bug Fixes

- **cli**: Add orchid-ai extras for document parsing and event handling
  ([`7985f59`](https://github.com/gadz82/orchid-cli/commit/7985f59bbc32f960a520e815e1d5cc893a807a81))


## v1.9.0 (2026-05-27)

### Bug Fixes

- **cli**: Correct PostgreSQL storage class import path in flower templates
  ([`7da6890`](https://github.com/gadz82/orchid-cli/commit/7da68906905e024ea8fcc8fc2c11b522e22f1fcc))

### Features

- **cli**: Add supervisor configuration support with memory and streaming options
  ([`8e7352a`](https://github.com/gadz82/orchid-cli/commit/8e7352a3d72b5dfa01f65ca9adea11e858cff099))

### Refactoring

- **cli**: Remove ChromaDB backend, replace with orchid-rag-chroma plugin
  ([`45ec2bd`](https://github.com/gadz82/orchid-cli/commit/45ec2bdee6c0e15d28d5c115a8e2da1849656941))

- **tests**: Replace _REGISTRY with TOOL_REGISTRY and improve test isolation
  ([`7c9ee5c`](https://github.com/gadz82/orchid-cli/commit/7c9ee5c63f4432ce94ab8b52b774c5c1d2bbb7aa))

### Testing

- Remove ChromaDB metadata filter tests
  ([`808f818`](https://github.com/gadz82/orchid-cli/commit/808f81809931a581e463623f058843f05c6c7c63))

- Remove ChromaRepository and Chroma scope filter tests
  ([`d016191`](https://github.com/gadz82/orchid-cli/commit/d016191e68b305b04ec0c4c9b4fdbfc7fade6058))


## v1.8.0 (2026-05-22)

### Bug Fixes

- Update orchid-ai dependency to version 1.8.2
  ([`feee011`](https://github.com/gadz82/orchid-cli/commit/feee0113ddcc3ff6d0ff94daa21ddab2e4aef309))

### Features

- **cli**: Add content path support for REPL and chat commands
  ([`1f4510b`](https://github.com/gadz82/orchid-cli/commit/1f4510b28f7cfbbc69fc39809115a6fbdfc07d2a))


## v1.7.0 (2026-05-20)

### Features

- Orchid generate flower command utility
  ([`7e48918`](https://github.com/gadz82/orchid-cli/commit/7e489184a21264b300f92b57087c705bceef2c9d))

- Orchid generate flower tests
  ([`367151a`](https://github.com/gadz82/orchid-cli/commit/367151a39d7c2ba53f4e35f723bf9869de6f9be4))


## v1.6.0 (2026-05-18)

### Bug Fixes

- Remove redundant CLAUDE.md symlinks across modules [skip ci]
  ([`d3b9117`](https://github.com/gadz82/orchid-cli/commit/d3b9117fecc552359ba871969053e4df2a2556a2))

### Features

- Update orchid-ai dependency to version 1.7.4
  ([`c56cd7b`](https://github.com/gadz82/orchid-cli/commit/c56cd7beb1d2cfe2f7b9b8e72363d75348e42b41))

- **cli**: Add tests for CancelScope, improve cancellation handling and file type checks
  ([`038d8c5`](https://github.com/gadz82/orchid-cli/commit/038d8c5ebecdffec40465d2e9b4fa5530481e8ee))

- **cli**: Skip .md files in apply_cli_config and add tests for file type handling
  ([`a4bc32c`](https://github.com/gadz82/orchid-cli/commit/a4bc32cdfaaad9a5ddd1a62bd523dce26174e236))


## v1.5.0 (2026-05-13)

### Documentation

- **cli**: Add related projects section to README
  ([`a5cb970`](https://github.com/gadz82/orchid-cli/commit/a5cb9708629d68ad7b83a43f8edbd01775d32116))

### Features

- **cli**: Add ChromaDB vector backend with scoped filtering and metadata translation
  ([`fd0feb3`](https://github.com/gadz82/orchid-cli/commit/fd0feb3d0666c3819852d562d7b31578f36c4a97))


## v1.4.0 (2026-05-10)

### Bug Fixes

- Test imports error
  ([`c9b9f54`](https://github.com/gadz82/orchid-cli/commit/c9b9f5484e2c761461594370ff4cd4aab2a75d94))

### Chores

- Bump orchid-ai dependency to v1.7.0
  ([`65e43a0`](https://github.com/gadz82/orchid-cli/commit/65e43a0e5e5019ce4fc95b824bb0c7a093d7cc06))

- Bump orchid-ai dependency to v1.7.1
  ([`8057525`](https://github.com/gadz82/orchid-cli/commit/80575253bf8e5513895ae95c2a849e109e2cbd0b))

### Documentation

- Add Pollen and Bloom operator panel, in-chat progress, and CLI tools
  ([`54d0666`](https://github.com/gadz82/orchid-cli/commit/54d0666ad33fe6e719eb190141b76f99cc95a3e8))

### Features

- Implement Pollen + Bloom subsystem and endpoints for event-driven workflows
  ([`3885374`](https://github.com/gadz82/orchid-cli/commit/38853740971688a04b57d561020ab6b1b7cb6bc3))

### Refactoring

- **docs**: Remove phased rollout references for streamlined documentation
  ([`db0d5b5`](https://github.com/gadz82/orchid-cli/commit/db0d5b54b05c6559f2e33e352b8736e1ace91044))


## v1.3.0 (2026-05-05)

### Chores

- Bump `orchid-ai` dependency to >=1.6.0 in `orchid-cli` and `orchid-api`
  ([`2aaedaf`](https://github.com/gadz82/orchid-cli/commit/2aaedafb417294f1780d80464b469467656fcd5d))

### Documentation

- Update Orchid API and MCP gateway README
  ([`9ff4750`](https://github.com/gadz82/orchid-cli/commit/9ff475005b06857afbc215b68c573b1a8c11a750))

### Features

- **cli**: Enable RecursiveIngestion for RAG index workflows
  ([`14bf9d4`](https://github.com/gadz82/orchid-cli/commit/14bf9d49b1eb6e5bf613497881765a0554d84f26))


## v1.2.1 (2026-05-04)

### Bug Fixes

- Broken unit tests by ensuring lock.
  ([`64f59fa`](https://github.com/gadz82/orchid-cli/commit/64f59fa71f6efe7f2a5fd51c35ea2fb48f6cf8c4))


## v1.2.0 (2026-04-29)

### Bug Fixes

- **cli**: Centralize session handling and warm-up lifecycle
  ([`cfe9c2d`](https://github.com/gadz82/orchid-cli/commit/cfe9c2de1cb39cd6002ff9a49bda2253ea25eee9))

- **cli**: Ensure lock file path respects test monkeypatching of _ORCHID_DIR, enhance test for
  temporary file cleanup
  ([`471de32`](https://github.com/gadz82/orchid-cli/commit/471de32d515a54a34d568f2c87a74f34c0b66ca1))

### Documentation

- **cli**: Clarify CLI OAuth independence
  ([`da14aa6`](https://github.com/gadz82/orchid-cli/commit/da14aa6dc5b571e63ce7bd10a633133979ceba82))

### Features

- Bump orchid-ai dependency to >=1.4.0 in CLI and API
  ([`9ed4940`](https://github.com/gadz82/orchid-cli/commit/9ed49401fe3c5337bef84a5c235e9bdc4bdaac3f))

- **cli**: Enhance chat commands and RAG indexing, improve security for token storage
  ([`74dac43`](https://github.com/gadz82/orchid-cli/commit/74dac433ce7731374f4bd4366cbee6c7ecf1dfc8))


## v1.1.4 (2026-04-22)

### Bug Fixes

- Mcp oauth management fixes to support http mcp oauth configuration.
  ([`1d7081d`](https://github.com/gadz82/orchid-cli/commit/1d7081d2a1f8caf90dcd91df785991324f7143c8))


## v1.1.3 (2026-04-21)

### Bug Fixes

- Reformatting answer
  ([`79e7866`](https://github.com/gadz82/orchid-cli/commit/79e7866b33bd0a265d1b117aece4ba549be6fcff))


## v1.1.2 (2026-04-21)

### Bug Fixes

- Missing mcp_token_store property accessor
  ([`9d930c9`](https://github.com/gadz82/orchid-cli/commit/9d930c984d9710944c8e9aa62b378bfbd3c6e1e5))


## v1.1.1 (2026-04-21)

### Bug Fixes

- Bump orchid-ai dependency to >=1.3.2 in CLI and API
  ([`2a20470`](https://github.com/gadz82/orchid-cli/commit/2a20470894399b42c26fefa738bc2a6dda81497c))

- **cli**: Add support for extra chat migrations package
  ([`56f73a9`](https://github.com/gadz82/orchid-cli/commit/56f73a9bcae8362c8425c6541c545be5d8858d5b))


## v1.1.0 (2026-04-17)

### Continuous Integration

- Grant pull-requests: write permission to the test job
  ([`3be63b5`](https://github.com/gadz82/orchid-cli/commit/3be63b545ceb1ccae4ac38e1a5853ea1d93307bc))

### Features

- Add HITL approval and checkpointer support to invoke
  ([`b2b62f6`](https://github.com/gadz82/orchid-cli/commit/b2b62f6d0a0e8417aa83d4ab0e155c087a0d18d6))

- Add LangGraph checkpointer integration for state persistence
  ([`ef2b6e8`](https://github.com/gadz82/orchid-cli/commit/ef2b6e81978128432cfc96eedbe2196f52abf86b))

- Add real-time streaming in interactive mode
  ([`61d19d1`](https://github.com/gadz82/orchid-cli/commit/61d19d19da7e2dde5e275f6011e92d24b5a8463d))

- Add shared hooks and utilities for CLI and frontend
  ([`035f7ca`](https://github.com/gadz82/orchid-cli/commit/035f7caef5a6cb59ed9c48192a61ba5d43a67cc7))

- Upgrade orchid-ai dependency to >=1.3.0
  ([`aad58d8`](https://github.com/gadz82/orchid-cli/commit/aad58d82501f872322785f97fcedf16977fafaee))

- **cli**: Extend vector-store indexing with new subcommands
  ([`26a31d9`](https://github.com/gadz82/orchid-cli/commit/26a31d94045e45964234303ae1f0eaa2447411e2))

- **cli**: Implement slash command dispatch table and plugin discovery
  ([`d83c8a0`](https://github.com/gadz82/orchid-cli/commit/d83c8a0b57f97465871d279d2824ebbf5a444fc7))

- **cli**: Refactor chat commands with extensible slash registry
  ([`2f9ee6a`](https://github.com/gadz82/orchid-cli/commit/2f9ee6a319e58578a8d802c119216256703bc6bb))


## v1.0.5 (2026-04-15)

### Bug Fixes

- Bump orchid-ai dependency to v1.2.14 in CLI and API
  ([`1400c62`](https://github.com/gadz82/orchid-cli/commit/1400c62664872c4daae8253e10325586a92a7c27))

- Simplify HTML content formatting and remove unused imports in mcp_auth and cli commands
  ([`abca379`](https://github.com/gadz82/orchid-cli/commit/abca379a216e63a57e52c43bb0c041449e740725))

- **cli**: MCP OAuth management commands and auto-authorization flow
  ([`7b69dbd`](https://github.com/gadz82/orchid-cli/commit/7b69dbd1a88bc4cbb76b7d35faeebc96472dd749))


## v1.0.4 (2026-04-14)

### Bug Fixes

- **auth**: Improve token expiration messaging and log formatting
  ([`7ef8e5b`](https://github.com/gadz82/orchid-cli/commit/7ef8e5b4bd33ade45b8ac07634c7b84e02808a5b))

- **auth**: Integrate OAuth 2.0 PKCE flow and token storage into CLI auth commands
  ([`e2df0b8`](https://github.com/gadz82/orchid-cli/commit/e2df0b8b261350382b94c8359abadab0007fdc6c))


## v1.0.3 (2026-04-14)

### Bug Fixes

- Built-in tools args propagation fix.
  ([`b12dd65`](https://github.com/gadz82/orchid-cli/commit/b12dd652fc61b35d5cc89a1d5df9dcc6fe841533))

- Built-in tools parameter declarations in config.
  ([`ce62103`](https://github.com/gadz82/orchid-cli/commit/ce621034f4ad307dd8203ab98b4eac4cc604969b))

- Fixing ruff errors and updated dependency
  ([`30bbf37`](https://github.com/gadz82/orchid-cli/commit/30bbf3701d30aa422d86a2906a8546377b026248))

- Implement multi-turn LLM tool loop package version update
  ([`97e0a1a`](https://github.com/gadz82/orchid-cli/commit/97e0a1a22d47ce4ad2387a68f9b588b8c81641f9))

- Tools result context injection.
  ([`fbdfdef`](https://github.com/gadz82/orchid-cli/commit/fbdfdef54da0e8a2df947b12fcfb8220cf488daf))


## v1.0.2 (2026-04-13)

### Bug Fixes

- Removing external dependencies and improving error handling and final outcome for the user.
  ([`2ebc6ef`](https://github.com/gadz82/orchid-cli/commit/2ebc6efb8f96e047a3dc649710967d4aece64ab4))


## v1.0.1 (2026-04-13)

### Bug Fixes

- Orchid-cli package description and readme update.
  ([`5055129`](https://github.com/gadz82/orchid-cli/commit/505512906fc9b6d88752940dd1c9b24a2eec8f0d))


## v1.0.0 (2026-04-13)

- Initial Release

## v1.0.0 (2026-04-10)

- Initial Release
