# Source Pack Implementation Map

The supplied Claude pack already implements the following as research filters/strategies. They are intentionally kept out of production until screened on KunalQuant data.

## Indicators
cluster_volume_profile.py
amd_power_of_three.py
oscillator_matrix.py
gamma_exposure.py
order_block_strength.py
structural_leg_profiler.py
smart_money_concepts.py
liquidity_delta_profiler.py
peak_activity_range.py
session_volume_ma.py
anchored_volume_profile.py
cvd_absorption.py
volume_surprise.py
machine_learning_ma.py
log_regression_channel.py

## Strategies / research tools
session_range_sweep_choch.py
sweep_and_engulf.py
rsi_divergence_optimizer.py
universal_signal_backtester.py

## Separate strategy
ol_oh_sweep_v1/

The supplied code was tested in isolation. This repository folder is the controlled destination for future adaptations. Production modules are not modified by this research pack.

## Next integration order

1. ATR structural trailing.
2. Opening Breakout V2 diagnostic comparison.
3. Gamma exposure as options regime context once historical chain coverage is verified.
4. SMC / volume-profile exit events.
5. CVD / liquidity modules only after real delta availability is established.
6. Independent OL/OH and session-sweep strategy research.
