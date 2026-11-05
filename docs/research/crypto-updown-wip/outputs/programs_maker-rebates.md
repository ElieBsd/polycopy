> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Maker Rebates Program

> Earn daily pUSD rebates by providing liquidity on Polymarket

Polymarket charges taker fees across multiple market categories. Fees are determined by the protocol at match time and fund a **Maker Rebates** program that pays daily pUSD rebates to liquidity providers.

***

## Why Maker Rebates

Deeper liquidity means tighter spreads, lower price impact, more reliable fills, and greater resilience during volatility. Maker Rebates incentivize **consistent, competitive quoting** so everyone gets a better trading experience.

***

## How Maker Rebates Work

* **Paid daily in pUSD:** Rebates are calculated and distributed every day.
* **Performance-based:** You earn based on the share of liquidity you provided that actually got taken.

### Eligibility

Place orders that add liquidity to the book and get filled (i.e., your liquidity is taken by another trader).

> [!NOTE]
>
> Maker rebates are funded by taker fees, so fills on markets with a 0% taker fee (including markets temporarily made fee-free during a fee holiday) earn **no maker rebate** for as long as the fee is 0.

### Payment

Rebates are paid daily in pUSD, directly to your wallet. A minimum accrued rebate of **\$1 pUSD** is required for a payout.

***

## Read Your Rebated Fees

Read a maker's rebate amounts for a calendar day to reconcile the program with
your accounting.

> [tab] TypeScript
>
> Call `fetchCurrentRebates()` using an existing `PublicClient` named `client`.
> If needed, [create a public client](https://docs.polymarket.com/getting-started/typescript.md#create-a-public-client).
> The method is also available on `SecureClient`.
>
> ```ts theme={null}
> const rebates = await client.fetchCurrentRebates({
>   date: "2026-10-06",
>   makerAddress: "0xFeA4cB3dD4ca7CefD3368653B7D6FF9BcDFca604",
> });
>
> for (const rebate of rebates) {
>   console.log(rebate.conditionId, rebate.rebatedFeesUsdc);
> }
> ```
>
> Each `RebatedFee` includes `date`, `conditionId`, `assetAddress`,
> `makerAddress`, and `rebatedFeesUsdc`. The amount is an exact USDC decimal string.
> Keep it as a string or use a decimal library for accounting. The method returns
> an empty array when the maker has no rebates for the requested date.

> [tab] Python
>
> Call `get_current_rebates()` using an existing `AsyncPublicClient` named `client`.
> If needed, [create a public client](https://docs.polymarket.com/getting-started/python.md#create-a-public-client).
> The method is also available on `AsyncSecureClient`. The synchronous clients
> provide the same method.
>
> ```python theme={null}
> rebates = await client.get_current_rebates(
>     date="2026-10-06",
>     maker_address="0xFeA4cB3dD4ca7CefD3368653B7D6FF9BcDFca604",
> )
>
> for rebate in rebates:
>     print(rebate.condition_id, rebate.rebated_fees_usdc)
> ```
>
> Each `RebatedFee` includes `date`, `condition_id`, `asset_address`,
> `maker_address`, and `rebated_fees_usdc`. The date is a `datetime.date` and the
> USDC amount is a `Decimal`. The method returns an empty tuple when the maker
> has no rebates for the requested date.

> [tab] API
>
> Request a date and the nonzero maker address without authentication.
>
> ```bash theme={null}
> curl -G "https://clob.polymarket.com/rebates/current" \
>   --data-urlencode "date=2026-10-06" \
>   --data-urlencode "maker_address=0xFeA4cB3dD4ca7CefD3368653B7D6FF9BcDFca604"
> ```
>
> Illustrative response:
>
> > [accordion] Output: Maker Rebates
> >
> > ```json theme={null}
> > [
> >   {
> >     "date": "2026-10-06",
> >     "condition_id": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
> >     "asset_address": "0x9c4E1703476E875070EE25b56A58B008CFb8FA78",
> >     "maker_address": "0xFeA4cB3dD4ca7CefD3368653B7D6FF9BcDFca604",
> >     "rebated_fees_usdc": "1.599840"
> >   }
> > ]
> > ```
>
> For a maker with no rows, the response is:
>
> ```json theme={null}
> null
> ```
>
> The response is an array when rebates exist, or `null` when there are no rows.
> Each entry contains `date`, `condition_id`,
> `asset_address`, `maker_address`, and `rebated_fees_usdc`, an exact USDC decimal
> string. This read is not paginated.

Use a valid `YYYY-MM-DD` calendar date and the maker's nonzero EVM address.
The requested date is not restricted to today.

***

## Funding

Maker Rebates are funded by taker fees collected in eligible markets. A percentage of these fees are redistributed to makers who keep the markets liquid. The rebate percentage differs by market type.

| Category | Maker Rebate | Distribution Method |
| - | - | - |
| Crypto | 20% | Fee-curve weighted |
| Sports | 15% | Fee-curve weighted |
| Finance | 25% | Fee-curve weighted |
| Politics | 25% | Fee-curve weighted |
| Economics | 25% | Fee-curve weighted |
| Culture | 25% | Fee-curve weighted |
| Weather | 25% | Fee-curve weighted |
| Other / General | 25% | Fee-curve weighted |
| Mentions | 25% | Fee-curve weighted |
| Tech | 25% | Fee-curve weighted |
| Geopolitics | — | Fee-free |

> [!NOTE]
>
> Polymarket collects taker fees in eligible markets across all fee-enabled categories.
> The rebate percentage is at the sole discretion of Polymarket
> and may change over time.

***

## Fee-Curve Weighted Rebates

Rebates are distributed using the **same formula as taker fees**. This ensures makers are rewarded proportionally to the fee value their liquidity generates.

For each filled maker order:

```text theme={null}
fee_equivalent = C × feeRate × p × (1 - p)
```

Where **C** = number of shares traded and **p** = price of the shares. The fee parameters differ by market type:

| Category | Taker Fee Rate | Maker Fee Rate |
| - | - | - |
| Crypto | 0.07 | 0 |
| Sports | 0.05 | 0 |
| Finance | 0.04 | 0 |
| Politics | 0.04 | 0 |
| Economics | 0.05 | 0 |
| Culture | 0.05 | 0 |
| Weather | 0.05 | 0 |
| Other / General | 0.05 | 0 |
| Mentions | 0.04 | 0 |
| Tech | 0.04 | 0 |
| Geopolitics | 0 | 0 |

Your daily rebate:

```text theme={null}
rebate = (your_fee_equivalent / total_fee_equivalent) * rebate_pool
```

Totals are calculated per market, so you only compete with other makers in the same market.

***

## Taker Fee Structure

Taker fees are calculated in pUSD and vary based on the share price. The fee amount in pUSD is symmetric around 50% probability — a trade at 30¢ incurs the same dollar fee as a trade at 70¢.

[Fee Curves](https://datawrapper.dwcdn.net/dJ74e/)

### Fee Tables (100 Shares)

For detailed fee tables for each market category, see the [Fees](https://docs.polymarket.com/trading/fees.md) page.

### Fee Precision

Fees are rounded to 5 decimal places. The smallest fee charged is 0.00001 pUSD. Anything smaller rounds to zero, so very small trades near the extremes may incur no fee at all.

***

## Which Markets Are Eligible

The following market categories have taker fees enabled and are eligible for maker rebates: Crypto, Sports, Finance, Politics, Economics, Culture, Weather, Tech, Mentions, and Other / General.

To confirm whether fees apply to a specific market, see [Trading
Fees](https://docs.polymarket.com/market-data/market-details.md#trading-fees) in Market Details.

***

## FAQ

> [accordion] How do I qualify for maker rebates
>
> Place orders that add liquidity to the book and get filled (i.e., your
> liquidity is taken by another trader).

> [accordion] When are rebates paid
>
> Daily, in pUSD. You must accrue at least \$1 in rebates before a payout is issued.

> [accordion] How are rebates calculated
>
> Rebates are proportional to your share of executed maker liquidity in each
> eligible market. Totals are calculated per market, so you only compete with
> other makers in the same market.

> [accordion] Where does the rebate pool come from
>
> Taker fees collected in eligible markets are allocated to the maker rebate
> pool and distributed daily.

> [accordion] Which markets have fees enabled
>
> Crypto, Sports, Finance, Politics, Economics, Culture, Weather, Tech, Mentions, and Other / General markets.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.