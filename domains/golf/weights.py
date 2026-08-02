"""How golf trades off conditions, travel and course fit.

Golf leans on conditions less than climbing does (65) because a mediocre-weather
round is still a round, while wet rock is simply not climbable — and leans on
fit more, because tee-time access, green fees and whether you can get on the
championship course dominate whether the trip was worth taking.
"""
W_CONDITIONS, W_TRAVEL, W_FIT = 50, 20, 30

COMPOSITE = {"conditions": W_CONDITIONS, "travel": W_TRAVEL, "fit": W_FIT}
