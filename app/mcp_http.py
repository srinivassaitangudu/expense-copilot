"""Hosted entrypoint. Does not expose the development REST API or any UI."""
from starlette.responses import JSONResponse
from starlette.routing import Route
from app.mcp_server import create_server


def create_app(config=None, verifier=None):
    server = create_server(config, remote=True, verifier=verifier)

    @server.custom_route('/healthz', methods=['GET'])
    async def health(request):
        return JSONResponse({'ok': True})

    application = server.streamable_http_app()
    async def metadata(request):
        return JSONResponse({
            'resource': str(server.settings.auth.resource_server_url).rstrip('/'),
            'authorization_servers': [str(server.settings.auth.issuer_url)],
            'scopes_supported': ['expenses:read', 'expenses:write'],
            'bearer_methods_supported': ['header'],
        })
    path = '/.well-known/oauth-protected-resource/mcp'
    application.router.routes = [route for route in application.routes if getattr(route, 'path', None) != path]
    application.router.routes.append(Route(path, metadata, methods=['GET']))
    return application
