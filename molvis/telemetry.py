"""Flushed measurements from real OpenMM minimization and dynamics reporters."""
import csv
import io
import json
import math
import time

FIELDS = ('sequence','stage','wall_time_s','step','time_ps','iteration','report_index',
          'potential_energy_kj_mol','kinetic_energy_kj_mol','total_energy_kj_mol',
          'temperature_k','target_temperature_k','restraint_energy_kj_mol','max_constraint_error')


class Measurements:
    def __init__(self, work, target):
        self.work=work; self.target=target; self.started=time.monotonic(); self.sequence=0
        self.json_file=(work/'measurements.jsonl').open('w',buffering=1)
        self.csv_file=(work/'measurements.csv').open('w',newline='',buffering=1)
        self.writer=csv.DictWriter(self.csv_file,fieldnames=FIELDS); self.writer.writeheader()

    def emit(self, stage, **values):
        self.sequence+=1
        record=dict.fromkeys(FIELDS)
        record.update(sequence=self.sequence,stage=stage,wall_time_s=time.monotonic()-self.started,
                      target_temperature_k=self.target,**values)
        if any(isinstance(value,(int,float)) and not math.isfinite(value) for value in record.values()):
            raise ValueError('Nonfinite OpenMM measurement; run stopped.')
        self.json_file.write(json.dumps(record,allow_nan=False)+'\n'); self.json_file.flush()
        self.writer.writerow(record); self.csv_file.flush()
        return record

    def minimization_reporter(self):
        import openmm as mm
        measurements=self
        class Reporter(mm.MinimizationReporter):
            def __init__(self):
                super().__init__(); self.reports=0
            def report(self, iteration, x, grad, args):
                self.reports+=1
                measurements.emit('minimization',iteration=iteration,report_index=self.reports,
                                  potential_energy_kj_mol=float(args['system energy']),
                                  restraint_energy_kj_mol=float(args['restraint energy']),
                                  max_constraint_error=float(args['max constraint error']))
                return False
        return Reporter()

    def dynamics_reporter(self, interval=10):
        from openmm import app
        measurements=self
        class Reporter(app.StateDataReporter):
            def __init__(self):
                self.stream=io.StringIO()
                super().__init__(self.stream,interval,step=True,time=True,potentialEnergy=True,
                                 kineticEnergy=True,totalEnergy=True,temperature=True)
            def report(self, simulation, state):
                super().report(simulation,state)
                rows=list(csv.DictReader(self.stream.getvalue().lstrip('#').splitlines()))
                row=rows[-1]
                measurements.emit('dynamics',step=int(row['Step']),time_ps=float(row['Time (ps)']),
                                  potential_energy_kj_mol=float(row['Potential Energy (kJ/mole)']),
                                  kinetic_energy_kj_mol=float(row['Kinetic Energy (kJ/mole)']),
                                  total_energy_kj_mol=float(row['Total Energy (kJ/mole)']),
                                  temperature_k=float(row['Temperature (K)']))
                (measurements.work/'dynamics.csv').write_text(self.stream.getvalue())
        return Reporter()

    def close(self):
        self.json_file.close(); self.csv_file.close()
