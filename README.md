# Junior Aladdin

NIFTY 50 auto market-observation + trading system.

A professional-grade technical analysis system that replicates a professional trader's brain — but processes more data simultaneously than any human can.

## Architecture

**5 Floors (bottom-up):**
1. **Floor 1** - Market Connection (Angel One data ingress)
2. **Floor 2** - Data Center (validation, cleaning, structuring, replay)
3. **Floor 3** - Calculation Engines (SMC, ICT, Technical, Options, Macro)
4. **Floor 4** - Department Heads (6 expert interpreters)
5. **Floor 5** - Captain (supreme judge, armed plans, conviction)

**3 Sides (cross-cutting):**
- **Side A** - Execution (ALERT/PAPER/REAL)
- **Side B** - Dashboard (operator terminal)
- **Side C** - Memory/Journal (event storage)

## Setup

```bash
# Clone and install
pip install -e .

# Install dev dependencies
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your Angel One API credentials

# Run tests
pytest tests/
```

## Requirements

- Python 3.11+
- Angel One API account (client_id, api_key, pin)
- Internet connection for live market data

## Philosophy

- **Survival First**: Protect capital above all
- **Confluence or Silence**: Multiple indicators aligning = trade
- **Context First**: Market regime, session, story before any signal
- **Trap Awareness**: Every signal questioned
- **Local-First**: Single laptop, zero paid cloud infrastructure

## Golden Chain

```
QUALITY (Floor 3) → CONFIDENCE (Floor 4) → CONVICTION (Floor 5)
```
