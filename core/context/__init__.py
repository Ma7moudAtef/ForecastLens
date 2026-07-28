"""Context-aware forecasting: the operating conditions of a period.

Industry-neutral by construction. The vocabulary is:

    unit          a production line, plant, site, warehouse, channel…
    stream        an output type, product family, category…
    driver        the volume measure a rate is expressed against
    context       the operating conditions of one period
    regime        a categorical label for a recurring context
    co_activity   which other unit/stream combinations were active

Nothing here knows what industry it is in. Two units running together, a
promotion week, a campaign batch and a high-utilization month are the same
phenomenon expressed through the same features.

The layer is arranged as three steps, each of which may end it:

    features.derive()   what the conditions were, per period and combination
    diagnose.diagnose() whether they change this series at all — runs for
                        EVERY series, always, and is reported either way
    matrix.build()      those conditions aligned to one series' own periods,
                        history and horizon alike

Only if all three succeed AND the effect is material do models 20–22 get to
compete, and then only on the same terms as every other model.

Anti-patterns this module exists to avoid, all of them tempting:

  - hardcoding "two lines running means more consumption" as a rule. It is a
    hypothesis; the data has to support it per material.
  - using a regressor that must itself be forecast. Every feature here comes
    from the driver plan or the planner's own calendar.
  - letting a p-value alone justify a model. Significance is not size.
  - fitting a level on three observations because the regime existed.
  - special-casing the new models in the competition so they win more often.
  - warning the user about a layer that simply does not apply to their data.
"""
