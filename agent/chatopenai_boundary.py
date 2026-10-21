"""Typed re-export of the installed provider; transport tests verify its narrow stub."""

from langchain_openai import ChatOpenAI

__all__ = ["ChatOpenAI"]
