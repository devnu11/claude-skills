from .test_s100_sleeps import *
def test_x(fake):
    pulse,_=make_pulse(fake)
    fake.clock += 120
    pulse._beat()
    print({k:v[:300] for k,v in fake.files.items()})
