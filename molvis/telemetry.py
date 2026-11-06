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

    def dynamics_reporter(self, interval=10, temperature_interval=None):
        from openmm import app
        measurements=self
        temperature_interval=temperature_interval or interval
        class Reporter(app.StateDataReporter):
            def __init__(self):
                self.stream=io.StringIO()
                super().__init__(self.stream,interval,step=True,time=True,potentialEnergy=True,
                                 kineticEnergy=True,totalEnergy=True,temperature=True)
            def describeNextReport(self, simulation):
                description=super().describeNextReport(simulation)
                description['steps']=min(interval-simulation.currentStep%interval,
                                         temperature_interval-simulation.currentStep%temperature_interval)
                return description
            def report(self, simulation, state):
                super().report(simulation,state)
                rows=list(csv.DictReader(self.stream.getvalue().lstrip('#').splitlines()))
                row=rows[-1]
                step=int(row['Step'])
                energy_due=step%interval==0; temperature_due=step%temperature_interval==0
                values=dict(step=step,time_ps=float(row['Time (ps)']))
                if energy_due:
                    values.update(potential_energy_kj_mol=float(row['Potential Energy (kJ/mole)']),
                                  kinetic_energy_kj_mol=float(row['Kinetic Energy (kJ/mole)']),
                                  total_energy_kj_mol=float(row['Total Energy (kJ/mole)']))
                if temperature_due: values['temperature_k']=float(row['Temperature (K)'])
                record=measurements.emit('dynamics',**values)
                output=measurements.work/'dynamics.csv'
                with output.open('a',newline='') as file:
                    writer=csv.DictWriter(file,fieldnames=FIELDS)
                    if file.tell()==0: writer.writeheader()
                    writer.writerow(record)
        return Reporter()

    def close(self):
        self.json_file.close(); self.csv_file.close()


class CoordinatePreview:
    """Latest C-alpha snapshot only; never a replacement for a trajectory."""
    def __init__(self, work, topology, interval_steps=10):
        self.work=work; self.interval_steps=interval_steps; self.last_step=None; self.sequence=0
        self.atoms=[(a.index,a.residue.chain.id) for a in topology.atoms()
                    if a.name=='CA' and a.element is not None and a.element.symbol=='C']

    def capture(self, simulation, state=None, force=False):
        if simulation.currentStep==self.last_step: return
        if not force and simulation.currentStep%self.interval_steps: return
        from openmm import unit
        if state is None: state=simulation.context.getState(getPositions=True)
        xyz=state.getPositions().value_in_unit(unit.angstrom)
        atoms=[dict(name='CA',record='ATOM',chain=chain,xyz=list(xyz[index])) for index,chain in self.atoms]
        if any(not math.isfinite(v) for atom in atoms for v in atom['xyz']):
            raise ValueError('Nonfinite coordinate preview; run stopped.')
        self.sequence+=1
        frame=dict(sequence=self.sequence,step=simulation.currentStep,
                   time_ps=state.getTime().value_in_unit(unit.picosecond),
                   atoms=atoms,chains=list(dict.fromkeys(chain for _,chain in self.atoms)))
        temporary=self.work/'coordinates.tmp'
        temporary.write_text(json.dumps(frame,allow_nan=False)); temporary.replace(self.work/'coordinates.json')
        self.last_step=simulation.currentStep

    def describeNextReport(self, simulation):
        return dict(steps=self.interval_steps-simulation.currentStep%self.interval_steps,
                    periodic=False,include=['positions'])

    def report(self, simulation, state):
        self.capture(simulation,state)
