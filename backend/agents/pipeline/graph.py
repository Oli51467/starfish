from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from agents.pipeline.nodes.checkpoints import human_checkpoint_1, human_checkpoint_2
from agents.pipeline.nodes.graph_build import graph_build_node
from agents.pipeline.nodes.insight import insight_node
from agents.pipeline.nodes.planner import planner_node
from agents.pipeline.nodes.report import report_node
from agents.pipeline.nodes.router import router_node
from agents.pipeline.nodes.save import save_node
from agents.pipeline.nodes.search import search_node
from agents.pipeline.nodes.synthesizer import synthesizer_node
from agents.pipeline.state import PipelineState


def build_pipeline_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("planner", planner_node)
    graph.add_node("router", router_node)
    graph.add_node("search", search_node)
    graph.add_node("graph_build", graph_build_node)
    graph.add_node("checkpoint_1", human_checkpoint_1)
    graph.add_node("checkpoint_2", human_checkpoint_2)
    graph.add_node("insight", insight_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("report", report_node)
    graph.add_node("save", save_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "router")
    graph.add_edge("router", "search")
    graph.add_edge("search", "checkpoint_1")
    graph.add_edge("checkpoint_1", "graph_build")
    graph.add_edge("graph_build", "checkpoint_2")
    graph.add_edge("checkpoint_2", "insight")
    graph.add_edge("insight", "synthesizer")
    graph.add_edge("synthesizer", "report")
    graph.add_edge("report", "save")
    graph.add_edge("save", END)

    return graph.compile()


@lru_cache
def get_pipeline_graph():
    return build_pipeline_graph()
