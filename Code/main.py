import numpy as np
import datetime
import statistics
from QuantConnect.Securities.Option import OptionPriceModels

class OptionTrading(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2016, 1, 2)  # Set Start Date
        self.SetEndDate(2017, 12, 31)
        self.SetCash(1000000)  # Set Strategy Cash
        
        #Stock/Option Universe
        self.stock_list = ["SPY"]
        
        self.equity = self.AddEquity("SPY", Resolution.Minute)
        #self.equity = self.AddEquity("SPY", Resolution.Minute)
        #self.equity = self.AddEquity("QQQ", Resolution.Minute)
        #self.equity = self.AddEquity("IWM", Resolution.Minute)
        
        optionA = self.AddOption("SPY")
        optionA.SetFilter(-15, 15, TimeSpan.FromDays(3),TimeSpan.FromDays(10)) #Set Options Universe
        optionA.PriceModel = OptionPriceModels.CrankNicolsonFD()
        '''
        optionB = self.AddOption("DIA")
        optionB.SetFilter(-15, 15, TimeSpan.FromDays(3),TimeSpan.FromDays(10))
        optionB.PriceModel = OptionPriceModels.CrankNicolsonFD()
        optionC = self.AddOption("QQQ")
        optionC.SetFilter(-15, 15, TimeSpan.FromDays(3),TimeSpan.FromDays(10))
        optionC.PriceModel = OptionPriceModels.CrankNicolsonFD()
        optionD = self.AddOption("IWM")
        optionD.SetFilter(-15, 15, TimeSpan.FromDays(3),TimeSpan.FromDays(10))
        optionD.PriceModel = OptionPriceModels.CrankNicolsonFD()
        '''
        self.SetWarmUp(TimeSpan.FromDays(60))
        
        #Lookback period for historic volatility in days
        self.HVPeriod = 30
        self.shortHVPeriod = 3
        
        #Set spread bounds for trade execution
        self.ShortBound = {"SPY": .247, "QQQ": 1, "DIA": 1, "IWM": 1}
        self.LongBound = {"SPY": 1, "QQQ": 1, "DIA": 1, "IWM": 1}
        self.ExtremeVolBoundLower = {"SPY": -1, "QQQ": -1, "DIA": -1, "IWM": -1}
        self.ExtremeVolBoundUpper = {"SPY": 1, "QQQ": 1, "DIA": 1, "IWM": 1}
        
        #type of strategy
        self.LongStrat = "Straddle"
        #self.LongStrat = "Strangle"
        self.ShortStrat = "Short Straddle"
        #self.ShortStrat = "Butterfly"
        #self.ShortStrat = "Condor"
        #self.ShortStrat = "Iron Condor"
        #self.ShortStrat = "Iron Butterfly"
        
        #status of strategy
        #"None" for not invested yet, or "Straddle", "Strangle", "Butterfly", "Condor", Iron Butterfly", "Iron Condor"
        self.status = {"SPY": "None", "QQQ": "None", "DIA": "None", "IWM": "None"}
        self.option_symbols = {"SPY": (None, None), "QQQ": (None, None), "DIA": (None, None), "IWM": (None, None)}
        self.expiration = {"SPY": None, "QQQ": None, "DIA": None, "IWM": None}
        
        #Trade Pause due to Vol
        self.vol_spike = {"SPY": 1, "QQQ": 1, "DIA": 1, "IWM": 1}
        
        #Trade Pause Length
        self.days_pause_left = {"SPY": 0, "QQQ": 0, "DIA": 0, "IWM": 0}
        self.pause_length = 3
        
        #Stop-Loss Triggers
        self.stop_loss = {"SPY": None, "QQQ": None, "DIA": None, "IWM": None}
        self.stop_loss_percentage_bound = .6
        self.stop_percentage = 1 + self.stop_loss_percentage_bound
        
        #Vix Indicator
        self.vix_indicator_on = False
        self.vix_spike = False
        self.vix_lookback_period = 30
        self.vix_stdevs = 2.25
        self.past_vix = None
        self.AddEquity("VIXY", Resolution.Minute)
        self.vix_pause = 3
        
        #Delta-Hedge
        self.delta_hedge_on = False
    
    #Function to return Daily Historical Close Data
    def getHistoricalDailyCloseData(self, symbol, days):
        bars = []
        slices = self.History(days, Resolution.Daily)
        for s in slices:
            bars.append(s.Bars[symbol].Close)
        return bars
    
    #Function that returns historical annual volatility with specified lookback period
    def CalculateHistoricVol(self, symbol, days):
        historic_data = self.getHistoricalDailyCloseData(symbol, days)
        returns_list = []
        for j in range(1, len(historic_data)):
            returns_list.append(np.log(historic_data[j]) - np.log(historic_data[j - 1])) #Log difference to approximate percentage
        daily_std = np.std(returns_list)
        annual_vol = daily_std * (252 ** .5)
        rounded_vol = round(annual_vol, 4)
        return rounded_vol
        
    #Delta Hedging Function
    def DeltaHedge(self, underlying_symbol, contractA, contractB, quantity, status):
        current_delta = (contractA.Greeks.Delta * quantity) + (contractA.Greeks.Delta * quantity)
        if status == "short":
            current_delta = current_delta * -1
        self.Log("Unhedged Delta: " + str(current_delta))
        hedge_order_number = -1 * int(round(current_delta))
        self.MarketOrder(underlying_symbol, hedge_order_number)
        self.Log("Order " + str(hedge_order_number) + " to Hedge")    
            
    def OnData(self, slice):
        
        if self.IsWarmingUp: 
            return
        
        #Liquidate and Stop Trading Short Strategy if VIX Spikes
        if self.vix_indicator_on:
            if self.past_vix == None or (self.Time.hour == 16 and self.Time.minute == 0):
                self.past_vix = self.getHistoricalDailyCloseData("VIXY", Resolution.Daily)
            avg_past_vix = statistics.mean(self.past_vix)
            std_past_vix = statistics.stdev(self.past_vix)
            current_vix = self.Securities["VIXY"].Price
            standard_devs = (current_vix - avg_past_vix) / std_past_vix 
            if (standard_devs > self.vix_stdevs):
                self.vix_spike = True
            else:
                self.vix_spike = False
            if self.vix_spike:
                for stock in self.stock_list:
                    if self.status[stock] == self.ShortStrat:
                        self.Log("Liquidate " + stock + " due to VIX indicator at " + str(standard_devs) + "Std Devs")
                        self.Liquidate(stock)
                        self.Liquidate(self.option_symbols[stock][0])
                        self.Liquidate(self.option_symbols[stock][1])
                        self.expiration[stock] = None
                        self.status[stock] = "None"
                    self.days_pause_left[stock] = self.vix_pause    
                
        
        #Liquidate on Expiration Day
        if self.Time.hour == 15 and self.Time.minute == 40:
            for stock in self.stock_list:
                if self.expiration[stock] == self.Time.strftime("%m/%d/%Y"):
                    self.Log("Expire: " + self.Time.strftime("%m/%d/%Y") + stock)
                    self.Liquidate(stock)
                    self.Liquidate(self.option_symbols[stock][0])
                    self.Liquidate(self.option_symbols[stock][1])
                    self.expiration[stock] = None
                    self.status[stock] = "None"
                    self.days_pause_left[stock] = self.vix_pause
                    
                    
        #Liquidate on Stop-Loss
        for stock in self.stock_list:
            if (self.status[stock] == self.ShortStrat) and (self.stop_loss != None):
                current_value = self.Securities[self.option_symbols[stock][0]].AskPrice + self.Securities[self.option_symbols[stock][1]].AskPrice
                if current_value > self.stop_loss[stock]:
                    self.Liquidate(stock)
                    self.Liquidate(self.option_symbols[stock][0])
                    self.Liquidate(self.option_symbols[stock][1])
                    self.expiration[stock] = None
                    self.status[stock] = "None"
                    self.days_pause_left[stock] = self.pause_length
                    self.stop_loss[stock] = None
                    self.Log("Stop Loss Triggered for " + stock)
        
        #Scan option information per hour
        if self.Time.minute == 0:
        
            for chain in slice.OptionChains:
                
                optionchain = chain.Value
                
                #Find options which has longest time to maturity
                farthest_expiry = max([x.Expiry for x in optionchain])
                optionchain = [x for x in optionchain if x.Expiry == farthest_expiry]
    
                #Differentiate calls and puts
                calls = [x for x in optionchain if x.Right == 0]
                puts = [x for x in optionchain if x.Right == 1]
                if len(calls) == 0 or len(puts) == 0: 
                    return
                
                #Calculate call and put implied volatility
                call_ATM = sorted(calls, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
                put_ATM = sorted(puts, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
                calls_iv = float(call_ATM.ImpliedVolatility)
                puts_iv = float(put_ATM.ImpliedVolatility)
                
                underlying_symbol = str(call_ATM.UnderlyingSymbol)
                
                if not(underlying_symbol in self.status.keys()):
                    self.Log("Key Not Found: " + underlying_symbol)
                    continue
                
                #Check if Trading Pause is Still in Effect for the Ticker
                if self.days_pause_left[underlying_symbol] > 0 and self.Time.hour == 16 and self.Time.minute == 0:
                    self.days_pause_left[underlying_symbol] -= 1
                    continue
                    
                if self.days_pause_left[underlying_symbol] > 0:
                    continue
                
                #calculate historic volatility
                historic_vol = self.CalculateHistoricVol(underlying_symbol, self.HVPeriod)
                short_historic_vol = self.CalculateHistoricVol(underlying_symbol, self.shortHVPeriod)
                
                #Compare historic vol indicators
                historic_vol_spread = short_historic_vol - historic_vol
                historic_vol_spread = round(historic_vol_spread, 4)
                
                #Compare implied vol with historic vol
                avg_call_put_iv = np.mean([calls_iv, puts_iv])
                hv_iv_spread = historic_vol - avg_call_put_iv #Spread = HV - IV
                hv_iv_spread = round(hv_iv_spread, 4)
                
                #Liquidate Current Holdings if Bounds are Breached
                if self.status[underlying_symbol] == self.LongStrat and (hv_iv_spread < self.LongBound[underlying_symbol]):
                    self.Liquidate(underlying_symbol)
                    self.Liquidate(self.option_symbols[underlying_symbol][0])
                    self.Liquidate(self.option_symbols[underlying_symbol][1])
                    self.Log("Liquidated Long Bound Breached " + underlying_symbol + str(hv_iv_spread))
                    self.status[underlying_symbol] = "None"
                    self.expiration[underlying_symbol] = None
                    continue
            
                if self.status[underlying_symbol] == self.ShortStrat and (hv_iv_spread > self.ShortBound[underlying_symbol]):
                    self.Liquidate(underlying_symbol)
                    self.Liquidate(self.option_symbols[underlying_symbol][0])
                    self.Liquidate(self.option_symbols[underlying_symbol][1])
                    self.Log("Liquidated Short Bound Breached: " + underlying_symbol + str(hv_iv_spread))
                    self.status[underlying_symbol] = "None"
                    self.expiration[underlying_symbol] = None
                    continue
                
                if (hv_iv_spread < self.ExtremeVolBoundLower[underlying_symbol]) or (hv_iv_spread > self.ExtremeVolBoundUpper[underlying_symbol]):
                    self.Liquidate(underlying_symbol)
                    self.Liquidate(self.option_symbols[underlying_symbol][0])
                    self.Liquidate(self.option_symbols[underlying_symbol][1])
                    self.Log("Extreme Vol Liquidate: " + underlying_symbol + str(hv_iv_spread))
                    self.status[underlying_symbol] = "None"
                    self.days_pause_left[underlying_symbol] = self.pause_length
                    self.expiration[underlying_symbol] = None
                    continue
                
                if (historic_vol_spread > self.vol_spike[underlying_symbol]):
                    self.Liquidate(underlying_symbol)
                    self.Liquidate(self.option_symbols[underlying_symbol][0])
                    self.Liquidate(self.option_symbols[underlying_symbol][1])
                    self.Log("Extreme Vol Spike Liquidate: " + underlying_symbol + str(hv_iv_spread))
                    self.Log("Near Minus Long Term Vol: " + str(historic_vol_spread))
                    self.status[underlying_symbol] = "None"
                    self.days_pause_left[underlying_symbol] = self.pause_length
                    self.expiration[underlying_symbol] = None
                    continue
                
                #Control unit to choose strategy based on HV-IV spread if no holdings
                strategy = "None"
                if (hv_iv_spread > self.LongBound[underlying_symbol]) and (hv_iv_spread <= self.ExtremeVolBoundUpper[underlying_symbol]):
                    strategy = self.LongStrat
                elif (hv_iv_spread < self.ShortBound[underlying_symbol]) and (hv_iv_spread >= self.ExtremeVolBoundLower[underlying_symbol]):
                    strategy = self.ShortStrat
               
    
                ## Long a Straddle (long at the money call and put)
                if strategy == "Straddle" and self.status[underlying_symbol] == "None":
              
                    call_ATM = sorted(calls, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
                    self.Debug(call_ATM)
                    put_ATM = sorted(puts, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
                    self.Debug(put_ATM)
                    # trade the contracts with the farthest expiration
                    call_symbol = call_ATM.Symbol
                    put_symbol = put_ATM.Symbol
                    
                    quantity = min(self.CalculateOrderQuantity(call_symbol, 0.025), self.CalculateOrderQuantity(put_symbol, 0.025))
                    #if quantity ==0 : continue
                    self.MarketOrder(call_symbol, quantity)
                    self.MarketOrder(put_symbol, quantity)
                    self.option_symbols[underlying_symbol]= (call_symbol, put_symbol)
                    self.status[underlying_symbol] = strategy
                    self.expiration[underlying_symbol] = call_ATM.Expiry.strftime("%m/%d/%Y")
                    self.Log("Enter Trade: " + underlying_symbol + " " + strategy)
                    self.Log("Current Vol Spread: " + str(hv_iv_spread))
                    #self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))
                    #self.Log( "call option strike price is "+str(call_ATM.Strike) + " stock price is "+str(call_ATM.UnderlyingLastPrice))
                    #self.Log( "put option strike price is "+str(put_ATM.Strike) + " stock price is "+str(put_ATM.UnderlyingLastPrice))  
                    if self.delta_hedge_on:
                        self.DeltaHedge(underlying_symbol, call_ATM, put_ATM, quantity, "long") 
                        
                ## Short a Straddle (short at the money call and put)
                if strategy == "Short Straddle" and self.status[underlying_symbol] == "None":
              
                    call_ATM = sorted(calls, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
                    put_ATM = sorted(puts, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
    
                    # trade the contracts with the farthest expiration
                    call_symbol = call_ATM.Symbol
                    put_symbol = put_ATM.Symbol
                    
                    quantity = -1 * min(self.CalculateOrderQuantity(call_symbol, 0.025), self.CalculateOrderQuantity(put_symbol, 0.025))
                    #quantity = -10
                    self.MarketOrder(call_symbol, quantity)
                    self.MarketOrder(put_symbol, quantity)
                    self.option_symbols[underlying_symbol] = (call_symbol, put_symbol)
                    self.expiration[underlying_symbol] = call_ATM.Expiry.strftime("%m/%d/%Y")
                    self.status[underlying_symbol] = strategy
                    self.stop_loss[underlying_symbol] = self.stop_percentage * (call_ATM.AskPrice + put_ATM.AskPrice) 
                    self.Log("Enter Trade: " + underlying_symbol + " " + strategy)
                    self.Log("Current HV-IV Vol Spread: " + str(hv_iv_spread))
                    self.Log("Trade Equity: " + str(quantity * (call_ATM.AskPrice + put_ATM.AskPrice)))
                    self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))
                    #self.Log( "call option strike price is "+str(call_ATM.Strike) + " stock price is "+str(call_ATM.UnderlyingLastPrice))
                    #self.Log( "put option strike price is "+str(put_ATM.Strike) + " stock price is "+str(put_ATM.UnderlyingLastPrice)) 
                    if self.Portfolio[put_symbol].Invested == False:
                        self.Liquidate(underlying_symbol)
                        self.Liquidate(self.option_symbols[underlying_symbol][0])
                        self.Liquidate(self.option_symbols[underlying_symbol][1])
                        self.status[underlying_symbol] = "None"
                        self.expiration[underlying_symbol] = None
                        continue
                    if self.delta_hedge_on:
                        self.DeltaHedge(underlying_symbol, call_ATM, put_ATM, quantity, "short")
                    
                ## Long Strangle (long out of the money call/put)
                if strategy == "Strangle":
                    tier_call = 1
                    tier_put = 1
    
                    calls_OTM = [x for x in calls if x.UnderlyingLastPrice - x.Strike < 0]
                    puts_OTM = [x for x in puts if x.UnderlyingLastPrice - x.Strike > 0]
                    if (len(calls_OTM)<tier_call+1) or (len(puts_OTM)<tier_put+1):
                        return
                    call_OTM = sorted(calls_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call]
                    put_OTM = sorted(puts_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_put]
                    
                    call_symbol = call_OTM.Symbol
                    put_symbol = put_OTM.Symbol
    
                    if self.status=="None":
                        #quantity = int(self.Portfolio.MarginRemaining * self.MarginUseRatio / (call_OTM.AskPrice + put_OTM.AskPrice) / 100)
                        #quantity = -1 * min(self.CalculateOrderQuantity(call_symbol, 0.025), self.CalculateOrderQuantity(put_symbol, 0.025))
                        quantity = -1
                        if quantity == 0 : continue
                        self.MarketOrder(call_symbol, quantity)
                        self.MarketOrder(put_symbol, quantity)
                        self.status = strategy
                        self.Log(strategy)
                        self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))
                        self.Log( "call option strike price is "+str(call_OTM.Strike) + " stock price is "+str(call_OTM.UnderlyingLastPrice))
                        self.Log( "put option strike price is "+str(put_OTM.Strike) + " stock price is "+str(put_OTM.UnderlyingLastPrice))   
                
                ## Long a Butterfly (buy one ITM and OTM call option and sell two ATM call options)        
                if strategy == "Butterfly":
                    tier_call_OTM = 5
                    tier_call_ITM = 5
    
                    call_ATM = sorted(calls, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
                    calls_OTM = [x for x in calls if x.UnderlyingLastPrice - x.Strike < 0]
                    calls_ITM = [x for x in calls if x.UnderlyingLastPrice - x.Strike > 0]
                    if (len(calls_OTM)<tier_call_OTM+1) or (len(calls_ITM)<tier_call_ITM+1):
                        return
                    call_OTM = sorted(calls_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_OTM]
                    call_ITM = sorted(calls_ITM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_ITM]
                    call_OTM_symbol = call_OTM.Symbol
                    call_ITM_symbol = call_ITM.Symbol
                    call_ATM_symbol = call_ATM.Symbol
    
                    if self.status=="None":
                        #quantity = int(self.Portfolio.MarginRemaining * self.MarginUseRatio 
                        #/ (call_OTM.AskPrice + call_ITM.AskPrice + 2*call_ATM.BidPrice) / 100)
                        quantity = 1
                        if quantity ==0 : continue
                        self.MarketOrder(call_OTM_symbol, quantity)
                        self.MarketOrder(call_ITM_symbol, quantity)          
                        self.MarketOrder(call_ATM_symbol, -quantity*2)
                        self.status = strategy
                        self.Log(strategy)
                        self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))
                        self.Log( "OTM call option strike price is "+str(call_OTM.Strike) + " stock price is "+str(call_OTM.UnderlyingLastPrice))
                        self.Log( "ITM call option strike price is "+str(call_ITM.Strike) + " stock price is "+str(call_ITM.UnderlyingLastPrice))
                        self.Log( "ATM call option strike price is "+str(call_ATM.Strike) + " stock price is "+str(call_ATM.UnderlyingLastPrice))
        
                ## Long a Condor (buy a call with strike price A (the lowest strike), sell a call with strike price B (the second lowest)
                ## sell a call with strike price C (the second highest), buy a call with strike price D (the highest strike))        
                if strategy == "Condor":
                    tier_call_OTM_buy = 2
                    tier_call_OTM_sell = 1
                    tier_call_ITM_buy = 2
                    tier_call_ITM_sell = 1
                    
                    calls_OTM = [x for x in calls if x.UnderlyingLastPrice - x.Strike < 0]
                    calls_ITM = [x for x in calls if x.UnderlyingLastPrice - x.Strike > 0]
                    call_OTM_buy = sorted(calls_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_OTM_buy]
                    call_OTM_sell = sorted(calls_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_OTM_sell]
                    call_ITM_buy = sorted(calls_ITM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_ITM_buy]
                    call_ITM_sell = sorted(calls_ITM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_ITM_sell]               
                    call_OTM_buy_symbol = call_OTM_buy.Symbol
                    call_OTM_sell_symbol = call_OTM_sell.Symbol
                    call_ITM_buy_symbol = call_ITM_buy.Symbol
                    call_ITM_sell_symbol = call_ITM_sell.Symbol
    
                    if self.status=="None":
                        quantity = int(self.Portfolio.MarginRemaining * self.MarginUseRatio 
                        / (call_OTM_buy.AskPrice + call_ITM_buy.AskPrice + call_OTM_sell.BidPrice + call_ITM_sell.BidPrice) / 100)
                        if quantity ==0 : continue
                        self.MarketOrder(call_OTM_buy_symbol, quantity)
                        self.MarketOrder(call_OTM_sell_symbol, -quantity)
                        self.MarketOrder(call_ITM_buy_symbol, quantity)
                        self.MarketOrder(call_ITM_sell_symbol, -quantity)
                        self.status = strategy
                        self.Log(strategy)
                        self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))
                        self.Log(" stock price is "+str(call_OTM_buy.UnderlyingLastPrice))
                        self.Log( "call_OTM_buy strike price is "+str(call_OTM_buy.Strike))
                        self.Log( "call_OTM_sell strike price is "+str(call_OTM_sell.Strike))
                        self.Log( "call_ITM_buy strike price is "+str(call_ITM_buy.Strike))
                        self.Log( "call_ITM_sell strike price is "+str(call_ITM_sell.Strike))
    
                ## Long a Iron Butterfly (buy one ITM, buy one OTM call option, buy one ATM call and sell one ATM call)        
                if strategy == "Iron Butterfly":
                    tier_call_OTM = 1
                    tier_call_ITM = 1
                    
                    call_ATM = sorted(calls, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[0]
                    calls_OTM = [x for x in calls if x.UnderlyingLastPrice - x.Strike < 0]
                    calls_ITM = [x for x in calls if x.UnderlyingLastPrice - x.Strike > 0]
                    call_OTM = sorted(calls_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_OTM]
                    call_ITM = sorted(calls_ITM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_ITM]
                    call_OTM_symbol = call_OTM.Symbol
                    call_ITM_symbol = call_ITM.Symbol
                    call_ATM_symbol = call_ATM.Symbol
    
                    if self.status=="None":
                        quantity = int(self.Portfolio.MarginRemaining * self.MarginUseRatio 
                        / (call_OTM.AskPrice + call_ITM.AskPrice +call_ATM.AskPrice + call_ATM.BidPrice) / 100)
                        if quantity ==0 : continue
                        self.MarketOrder(call_OTM_symbol, -quantity)
                        self.MarketOrder(call_ITM_symbol, quantity)          
                        self.MarketOrder(call_ATM_symbol, quantity)
                        self.MarketOrder(call_ATM_symbol, -quantity)
                        self.status = strategy
                        
                        self.Log(strategy)
                        self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))
                        self.Log( "OTM call option strike price is "+str(call_OTM.Strike) + " stock price is "+str(call_OTM.UnderlyingLastPrice))
                        self.Log( "ITM call option strike price is "+str(call_ITM.Strike) + " stock price is "+str(call_ITM.UnderlyingLastPrice))
                        self.Log( "ATM call option strike price is "+str(call_ATM.Strike) + " stock price is "+str(call_ATM.UnderlyingLastPrice))
                        self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))    
                        
                ## Long a Iron Condor (buy one ITM, but one OTM call option, buy one ATM call and sell one ATM call) 
                if strategy == "Iron Condor":
                    tier_call_OTM_buy = 1
                    tier_call_OTM_sell = 0
                    tier_put_OTM_buy = 1
                    tier_put_OTM_sell = 0
                    
                    calls_OTM = [x for x in calls if x.UnderlyingLastPrice - x.Strike < 0]
                    puts_OTM = [x for x in puts if x.UnderlyingLastPrice - x.Strike > 0]
                    call_OTM_buy = sorted(calls_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_OTM_buy]
                    call_OTM_sell = sorted(calls_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_call_OTM_sell]
                    put_OTM_buy = sorted(puts_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_put_OTM_buy]
                    put_OTM_sell = sorted(puts_OTM, key = lambda x: abs(x.UnderlyingLastPrice - x.Strike))[tier_put_OTM_sell]
                    
                    call_OTM_buy_symbol = call_OTM_buy.Symbol
                    call_OTM_sell_symbol = call_OTM_sell.Symbol
                    put_OTM_buy_symbol = put_OTM_buy.Symbol
                    put_OTM_sell_symbol = put_OTM_sell.Symbol
    
                    if self.status=="None":
                        quantity = int(self.Portfolio.MarginRemaining * self.MarginUseRatio 
                        / (call_OTM_buy.AskPrice + call_OTM_sell.BidPrice +put_OTM_buy.AskPrice + put_OTM_sell.BidPrice) / 100)
                        if quantity ==0 : continue
                        self.MarketOrder(call_OTM_sell_symbol, -quantity)
                        self.MarketOrder(put_OTM_sell_symbol, -quantity)
                        self.MarketOrder(call_OTM_buy_symbol, quantity)
                        self.MarketOrder(put_OTM_buy_symbol, quantity)
                        self.status = strategy
                        
                        self.Log(strategy)
                        self.Log("Current Margin Remaining is "+str(self.Portfolio.MarginRemaining))
                        self.Log(" stock price is "+str(call_OTM_buy.UnderlyingLastPrice))
                        self.Log( "OTM call option to buy strike price is "+str(call_OTM_buy.Strike))
                        self.Log( "OTM call option to sell strike price is "+str(call_OTM_sell.Strike))
                        self.Log( "OTM put option to buy strike price is "+str(put_OTM_buy.Strike))
                        self.Log( "OTM put option to sell strike price is "+str(put_OTM_sell.Strike))