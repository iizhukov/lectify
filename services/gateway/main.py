import os
import uvicorn
from src.app import create_app


def configure():
    from generated.logger import setup_logging
    from generated.observability.observability import configure_tracing, configure_metrics
    setup_logging()
    configure_tracing()
    configure_metrics()


app = create_app(configure=configure)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('GATEWAY_PORT', '8080')))
