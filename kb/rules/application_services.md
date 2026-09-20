## [SVC-HTTP] Plan HTTP services on their specified components
Rule-ID: SVC-HTTP
Kind: rule
Mode: all
Status: target_specification
Keywords: services, http, nginx, apache, server, listen, document_root, port 80
Applies: A component declares an HTTP server service.
Required: Preserve implementation, enabled state, listen address/port, document root and supplied content/settings. Plan package, configuration and service operations in dependency order on that component. Bind the server inside its lab runtime when using isolated nodes.
Forbidden: Do not install on every host, expose a public listener, enable a disabled service or rewrite routing to make HTTP reachable.
Expected: The plan specifies the requested service configuration; access still depends on actual routing, filtering and service state.
Verify: Downstream checks distinguish listening service, HTTP response and end-to-end network reachability.
Sources: NGINX-HTTP, PROJECT
Related: AUTO-001, AUTO-002, CORE-001

## [SVC-HTTPS] Preserve TLS configuration and secret references
Rule-ID: SVC-HTTPS
Kind: rule
Mode: all
Status: target_specification
Keywords: services, https, TLS, certificate, private_key, port 443
Applies: A component requests an HTTPS endpoint.
Required: Plan supplied listener, server name, certificate/key references and TLS settings on the exact target. Describe dependencies for certificate provisioning and service reload without resolving secrets.
Forbidden: Do not invent certificates, credentials or a public domain; do not change HTTPS to HTTP or silently disable TLS verification.
Expected: Structured service intentions retain the input's TLS requirements and unresolved external references.
Verify: External implementation must check certificate availability and the deployed endpoint.
Sources: PROJECT
Related: SVC-HTTP, AUTO-001
