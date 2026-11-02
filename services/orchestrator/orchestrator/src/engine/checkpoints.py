"""Application-owned durable stream storage. Every write is fenced by the DB lease."""
import asyncio
from sqlalchemy import delete,select
from generated.db.transactions import run_transaction
from generated.stream_router import StreamChunkData
from generated.observability.operations import transfer
from src.engine.dispatch import guard_execution_write
from src.models import StreamCheckpointFrameModel as Frame,WorkflowNodeExecutionModel as Node
from src.engine.attempts import begin as begin_attempt


class StreamCheckpoints:
    def __init__(self,factory,execution_id,ownership):
        self.factory,self.execution_id,self.ownership=factory,execution_id,ownership

    async def guard(self,session):
        if not await guard_execution_write(session,self.execution_id,self.ownership):
            raise RuntimeError('Execution stream lease was lost')

    async def begin(self,node_id):
        async def transaction(session):
            await self.guard(session)
            node=await session.scalar(select(Node).where(Node.execution_id==self.execution_id,Node.node_id==node_id))
            if node is None: raise RuntimeError('Execution node is not persisted')
            if node.state=='COMPLETED':
                if not node.checkpoint_ready:
                    raise RuntimeError('Historical node has no durable checkpoint; start a new execution')
                return True
            await session.execute(delete(Frame).where(Frame.execution_id==self.execution_id,Frame.node_id==node_id))
            node.state,node.progress_percent,node.checkpoint_ready='PROCESSING',0,False
            node.output_artifacts={}
            node.error_message=None
            await begin_attempt(session,self.execution_id,node_id,self.ownership)
            return False
        return await run_transaction(self.factory,transaction)

    async def append(self,node_id,position,frame):
        async def transaction(session):
            await self.guard(session)
            session.add(Frame(execution_id=self.execution_id,node_id=node_id,position=position,
                stream_name=frame.stream_name,sequence=frame.sequence,payload=frame.payload,
                is_last=frame.is_last,frame_metadata=dict(frame.metadata or {})))
        await run_transaction(self.factory,transaction)
        transfer('checkpoint','persist','output',len(frame.payload))

    async def replay(self,node_id,inputs):
        async def drain():
            async for _ in inputs: pass
        consuming=asyncio.create_task(drain())
        try:
            position=0
            while True:
                async with self.factory() as session:
                    await self.guard(session)
                    rows=list(await session.scalars(select(Frame).where(Frame.execution_id==self.execution_id,
                        Frame.node_id==node_id,Frame.position>=position).order_by(Frame.position).limit(16)))
                    await session.commit()
                if not rows: break
                for row in rows:
                    if row.position!=position: raise RuntimeError('Durable stream checkpoint is incomplete')
                    position+=1
                    transfer('checkpoint','replay','output',len(row.payload))
                    yield StreamChunkData(stream_name=row.stream_name,sequence=row.sequence,payload=row.payload,
                        is_last=row.is_last,metadata=row.frame_metadata)
            await consuming
        finally:
            if not consuming.done(): consuming.cancel()
            await asyncio.gather(consuming,return_exceptions=True)
