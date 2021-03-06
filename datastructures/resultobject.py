import cvxpy as cp
import numpy as np
import pandas as pd
import statistics as st
import matplotlib.pyplot as plt
from datastructures.inputstructs import AgentData, MarketSettings
from constraintbuilder.ConstraintBuilder import ConstraintBuilder
from plotting_processing_functions.plot_pool_clearing import prep_plot_market_clearing_pool
import itertools


class ResultData:
    def __init__(self, name, prob: cp.problems.problem.Problem,
                 cb: ConstraintBuilder,
                 agent_data: AgentData, settings: MarketSettings):
        """
        Object to store relevant outputs from a solved market problem.
        Initialization only extracts necessary values from the optimization
        Functions can be used to compute other quantities or generate plots

        :param name: str
        :param prob: cvxpy problem object
        :param cb: ConstraintBuilder used for cvxpy problem
        :param agent_data: AgentData object
        :param settings: MarketSettings object
        """
        #
        self.name = name
        self.market = settings.market_design

        if prob.status in ["infeasible", "unbounded"]:
            self.optimal = False
            raise Warning("problem is not solved to an optimal solution. result object will not contain any info")
        else:
            self.optimal = True
            # store values of the optimized variables -------------------------------------------------------
            variables = prob.variables()
            varnames = [prob.variables()[i].name() for i in range(len(prob.variables()))]
            self.Pn = pd.DataFrame(variables[varnames.index("Pn")].value, columns=agent_data.agent_name)
            self.Ln = pd.DataFrame(variables[varnames.index("Ln")].value, columns=agent_data.agent_name)
            self.Gn = pd.DataFrame(variables[varnames.index("Gn")].value, columns=agent_data.agent_name)
            if settings.market_design == "p2p":
                # extract trade variable - a square dataframe for each time index
                self.Tnm = [pd.DataFrame(variables[varnames.index("Tnm_" + str(t))].value,
                                         columns=agent_data.agent_name, index=agent_data.agent_name)
                            for t in range(settings.nr_of_h)]

            # get values related to duals  ----------------------------------------
            if settings.market_design == "pool":
                self.shadow_price = cb.get_constraint(str_="powerbalance").dual_value
                self.shadow_price = pd.DataFrame(self.shadow_price, columns=["uniform price"])
            elif settings.market_design == "p2p":
                self.shadow_price = [pd.DataFrame(index=agent_data.agent_name, columns=agent_data.agent_name)
                                     for t in settings.timestamps]
                for t in settings.timestamps:
                    for i, j in itertools.product(range(agent_data.nr_of_agents), range(agent_data.nr_of_agents)):
                        # if not i == j:
                        if j >= i:
                            constr_name = "reciprocity_t" + str(t) + str(i) + str(j)
                            self.shadow_price[t].iloc[i, j] = cb.get_constraint(str_=constr_name).dual_value
                            self.shadow_price[t].iloc[j, i] = - self.shadow_price[t].iloc[i, j]
            elif settings.market_design == "community":
                self.shadow_price = "TODO!"

            # initialize empty slots for uncomputed result quantities
            self.QoE = None
            self.social_welfare_h = None
            self.settlement = None
            self.compute_output_quantities(settings, agent_data)

    # a function to make all relevant output variables
    def compute_output_quantities(self, settings, agent_data):
        # get shadow price, Qoe, for different markets --------------------------------------------------
        if settings.market_design == "pool":
            self.QoE = np.nan * np.ones(settings.nr_of_h)
            # raise Warning("QoE not implemented for pool")
        elif settings.market_design == "p2p":
            # QoE
            self.QoE = pd.DataFrame(index=range(settings.nr_of_h),columns=["QoE"])
            for t in range(0, settings.nr_of_h):
                lambda_j = []
                for a1 in agent_data.agent_name:
                    for a2 in agent_data.agent_name:
                        if self.Pn[a1][t] != 0:  # avoid #DIV/0! error
                            lambda_j.append(agent_data.cost[a1][t] * self.Tnm[t][a1][a2] / self.Pn[a1][t])
                        if self.Ln[a1][t] != 0:  # avoid #DIV/0! error
                            lambda_j.append(agent_data.util[a1][t] * self.Tnm[t][a1][a2] / self.Ln[a1][t])
                if (max(lambda_j) - min(lambda_j)) != 0:  # avoid #DIV/0! error
                    self.QoE["QoE"][t] = (1 - (st.pstdev(lambda_j) / (max(lambda_j) - min(lambda_j))))
                else:
                    pass
            # self.qoe = np.average(self.QoE) # we only need it for each hour.
        elif settings.market_design == "community":
            self.QoE = np.nan * np.ones(settings.nr_of_h)
            # raise Warning("community shadow price and QoE not implemented yet \n")

        # hourly social welfare an array of length settings.nr_of_h
        self.social_welfare_h = pd.DataFrame(index=range(settings.nr_of_h),columns=["Social Welfare"])
        for t in range(0, settings.nr_of_h):
            total_cost = np.sum(np.multiply(agent_data.cost.T[t], self.Gn.T[t]))
            total_util = np.sum(np.multiply(agent_data.util.T[t], self.Ln.T[t]))
            self.social_welfare_h["Social Welfare"][t] = (total_cost - total_util)
        
        
        
        # TODO compute settlement for each hour!!
        # ObfFun not considering penalties; Must be equal to social_welfare except when considering preferences
        #self.settlement = (np.sum(np.sum(np.multiply(agent_data.cost, self.Gn))) -
                           #np.sum(np.sum(np.multiply(agent_data.util, self.Ln))))
        #self.settlement = np.zeros([settings.nr_of_h,len(agent_data.agent_name)])
        self.settlement = pd.DataFrame(index=range(settings.nr_of_h),columns=agent_data.agent_name)
        for t in range(0, settings.nr_of_h):
            for agent in agent_data.agent_name:
                self.settlement[agent][t] = agent_data.cost[agent][t]*self.Gn[agent][t] - agent_data.util[agent][t]*self.Ln[agent][t]
        

    # a function working on the result object, to create plots
    def plot_market_clearing(self, period: int, settings: MarketSettings, agent_data: AgentData, outfile: str):
        """
        makes a plot in the file named at path outfile.
        """
        if not period <= settings.nr_of_h:
            raise ValueError("period should be in range(settings.nr_of_h)")

        if self.market == "pool":
            data1, data2, yy_gen, yy_load = prep_plot_market_clearing_pool(period, agent_data)
            # Plotting
            plt.step(data1, yy_gen)  # Generation curve
            plt.step(data2, yy_load)  # Load curve
            plt.plot(np.sum(self.Ln.T[period]), abs(self.shadow_price.T[period]), 'ro')  # (heat negotiated,shadow price)
            plt.ylabel('Price (€/kWh)')
            plt.xlabel('Heat (kWh)')
            plt.savefig(fname=outfile)
            return "success"
        else:
            return print("not implemented yet")
