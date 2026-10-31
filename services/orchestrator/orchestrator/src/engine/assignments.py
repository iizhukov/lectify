"""Bind trusted deployment grants to the execution lease and launch policy."""
from generated.container_assignments import ContainerRuntimeAssignments
from src.engine.launch import prepare_worker_launch, launch_on_worker


def runtime_assignments(factory, workers, images, grants):
    async def prepare(**scope):
        async with factory() as session:
            attempt_id, daemon_id, _ = await prepare_worker_launch(session,workers,**scope)
            await session.commit()
        return {'attempt_id':attempt_id,'daemon_id':daemon_id}

    def launch(**scope):
        return launch_on_worker(factory,workers,**scope)

    return ContainerRuntimeAssignments(images=images,prepare=prepare,launch=launch,grants=grants)
