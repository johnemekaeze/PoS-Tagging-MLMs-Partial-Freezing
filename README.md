# Partial Freezing of Multilingual Models for PoS Tagging

## Objective
We explored the impact of partial layer freezing on the fine-tuning of a distilled multilingual model for the task of Part-of-Speech (PoS) tagging. The overriding objective is to selectively freeze layers of a chosen distilled model (DistilBERT base cased) to  preserve pre-trained knowledge while adapting the model to specific tasks, while reducing computational cost. 

## Dataset 
We used the subsets of the Universal Dependencies dataset, UD English EWT and UD Naija NSC, focusing on ensuring manageable training times. The dataset can be found at https://universaldependencies.org 

## Repository
This repository contains the data, code and a report detailing the approach to the freezing and fine-tuning processes, as well as the results obtained and analysis.
