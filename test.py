# QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
# Lean Algorithmic Trading Engine v2.0. Copyright 2014 QuantConnect Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from AlgorithmImports import *
import math

class SpyLeapCallStrategy(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2010, 1, 1)
        self.set_end_date(2012, 12, 31)
        self.set_cash(100000)

        # Underlying SPY
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol

        # Add SPY options and store its symbol
        option = self.add_option("SPY", Resolution.DAILY)
        option.set_filter(self.option_filter)
        self.option_symbol_obj = option.symbol  # store the option "root symbol" here

        self.call_option_symbol = None
        self.put_option_symbol = None
        self.trading_years = set()
        self.position = 0
        self.initial_transaction = False
        self.new_year_delay = 0
        self.share_ratio_in_value = 0.8
        self.call_cost_basis = 0.0
        self.put_cost_basis = 0.0
        self.stock_year_start_value = 0.0
        self.buy_and_hold_finished = False

    def option_filter(self, universe):
        return universe.strikes(-5, 5).expiration(365, 1500)

    def find_atm_leap(self, chain, is_call):
        right = None
        if is_call:
            right = OptionRight.CALL
        else:
            right = OptionRight.PUT
        option = [x for x in chain if x.right == right]
        if not option:
            return None
        farthest_expiry = max(x.expiry for x in option)
        candidates = [c for c in option if c.expiry == farthest_expiry]
        underlying_price = self.securities[self.spy].price
        atm_contract = sorted(candidates, key=lambda x: abs(x.strike - underlying_price))[0]
        return atm_contract

    def calculate_positions(self, atm_call_contract, atm_put_contract):
        # return self.stock_80_call_20(atm_call_contract)
        # return self.buy_and_hold()
        return self.enhanced_buy_and_hold(atm_call_contract, atm_put_contract)

    def buy_and_hold(self):
        if self.buy_and_hold_finished:
            return 0, 0, 0

        total_value = self.portfolio.total_portfolio_value
        stock_price = self.securities[self.spy].price
        shares = int(total_value / stock_price)
        self.buy_and_hold_finished = True
        return shares, 0, 0

    def stock_80_call_20(self, atm_call_contract):
        total_value = self.portfolio.total_portfolio_value
        stock_value = self.portfolio[self.spy].holdings_value
        target_stock_value = total_value * self.share_ratio_in_value
        target_call_value = total_value - target_stock_value
        difference_stock_value = target_stock_value - stock_value
        stock_price = self.securities[self.spy].price

        shares = int(difference_stock_value / stock_price)

        contract_cost = atm_call_contract.ask_price * 100
        call_contract_count = int((target_call_value) / contract_cost)

        return shares, call_contract_count, 0

    def enhanced_buy_and_hold(self, atm_call_contract, atm_put_contract):
        single_share_call_atm = atm_call_contract.ask_price
        single_share_put_atm = atm_put_contract.ask_price
        single_share_total = single_share_call_atm + single_share_put_atm + self.securities[self.spy].price

        total_shares = math.floor(self.portfolio.total_portfolio_value / single_share_total)
        contract_count = math.ceil(total_shares / 100)

        curr_stock_shares = self.portfolio[self.spy].quantity
        shares_to_buy = total_shares - curr_stock_shares

        return shares_to_buy, contract_count, contract_count

    def year_start_rebalance(self, slice):
        chain = slice.option_chains.get(self.option_symbol_obj)
        if not chain:
            return False

        self.debug(f"===========================")
        self.debug(f"Start year {self.time.year}")
        self.debug(f"===========================")

        # Find the options we are interested in
        atm_call_contract = self.find_atm_leap(chain, True)
        atm_put_contract = self.find_atm_leap(chain, False)
        self.call_option_symbol = atm_call_contract.symbol
        self.put_option_symbol = atm_put_contract.symbol

        # Now figure out the positions based on our strategy and available
        # options
        shares_to_purchase, call_contracts, put_contracts = \
            self.calculate_positions(atm_call_contract, atm_put_contract)

        if shares_to_purchase > 0:
            self.market_order(self.spy, shares_to_purchase)
            self.debug(f"Bought {shares_to_purchase} shares of {self.option_symbol_obj} at {self.securities[self.spy].price} on {self.time.date()}")
        if call_contracts > 0:
            self.market_order(self.call_option_symbol, call_contracts)
            self.debug(f"Bought {call_contracts} call contracts of {self.call_option_symbol} at {atm_call_contract.ask_price} on {self.time.date()}")
            self.debug(f"Option expiration date: {atm_call_contract.expiry.date()}")
            self.debug(f"Option strike price: {atm_call_contract.strike}")
        if put_contracts > 0:
            self.market_order(self.put_option_symbol, put_contracts)
            self.debug(f"Bought {put_contracts} put contracts of {self.put_option_symbol} at {atm_put_contract.ask_price} on {self.time.date()}")
            self.debug(f"Option expiration date: {atm_put_contract.expiry.date()}")
            self.debug(f"Option strike price: {atm_put_contract.strike}")

        current_price = self.securities[self.spy].price
        self.debug(f"Current underlying price: {current_price}")

        self.call_cost_basis = call_contracts * atm_call_contract.ask_price * 100
        self.put_cost_basis = put_contracts * atm_put_contract.ask_price * 100
        self.stock_year_start_value = self.portfolio[self.spy].holdings_value + shares_to_purchase * self.securities[self.spy].price

        self.debug(f"===========================")
        return True

    def is_last_trading_day_of_year(self):
        next_trading_day = self.securities[self.spy].exchange.hours.get_next_trading_day(self.time)
        return next_trading_day.year > self.time.year

    def year_end_exit(self):
        if not self.is_last_trading_day_of_year():
            return

        self.debug(f"Net portfolio value: {self.portfolio.total_portfolio_value}")

        call_contracts = self.portfolio[self.call_option_symbol].quantity
        if self.call_option_symbol and call_contracts != 0:
            option_price = self.Securities[self.call_option_symbol].Price
            curr_holding_value = self.portfolio[self.call_option_symbol].holdings_value
            profit = curr_holding_value - self.call_cost_basis
            growth = profit * 100 / self.call_cost_basis

            self.liquidate(self.call_option_symbol)

            self.debug(f"Liquidating {call_contracts} call contracts at price {option_price} on {self.time.date()}")
            self.debug(f"Call option profit is {profit}. Growth {growth}")
            self.call_option_symbol = None
            self.call_cost_basis = 0

        put_contracts = self.portfolio[self.put_option_symbol].quantity
        if self.put_option_symbol and put_contracts != 0:
            option_price = self.Securities[self.put_option_symbol].Price
            curr_holding_value = self.portfolio[self.put_option_symbol].holdings_value
            profit = curr_holding_value - self.put_cost_basis
            growth = profit * 100 / self.put_cost_basis

            self.liquidate(self.put_option_symbol)

            self.debug(f"Liquidating {put_contracts} put contracts at price {option_price} on {self.time.date()}")
            self.debug(f"Put option profit is {profit}. Growth {growth}")
            self.put_option_symbol = None
            self.put_cost_basis = 0

        curr_holding_value = self.portfolio[self.spy].holdings_value
        profit = curr_holding_value - self.stock_year_start_value
        growth = profit * 100 / self.stock_year_start_value
        self.debug(f"Stock profit is {profit}. Growth {growth}")

        self.new_year_delay = 3

        self.debug(f"===========================")
        self.debug(f"Finish year {self.time.year}")
        self.debug(f"===========================")

    def on_data(self, slice: Slice):
        year = self.time.year

        if year not in self.trading_years and self.new_year_delay == 0:
            if self.year_start_rebalance(slice):
                self.trading_years.add(year)

        if self.new_year_delay > 0:
            self.new_year_delay = self.new_year_delay - 1

        self.year_end_exit()
