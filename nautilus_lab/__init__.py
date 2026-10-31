"""Optional research lab: backtest the momentum strategy on NautilusTrader.

Kept out of the core bot on purpose: `copybot` stays five hash-locked dependencies, and this
package (which needs the much heavier `nautilus_trader`) is installed only when you want to
research. See nautilus_lab/README.md.
"""
