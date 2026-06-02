"""In-memory store adapter wrapping existing lists."""

from typing import Optional
from app.db.store_interface import Store


class InMemoryStore(Store):
    """Wraps the existing in-memory lists from memory_store module."""

    def __init__(self, ms):
        """ms = the memory_store module."""
        self.ms = ms

    def get_project(self, project_id):
        return next((p for p in self.ms.projects if p.id == project_id), None)

    def list_projects(self):
        return list(self.ms.projects)

    def create_project(self, project):
        self.ms.projects.append(project)
        return project

    def delete_project(self, project_id):
        self.ms.projects[:] = [p for p in self.ms.projects if p.id != project_id]

    def get_sample(self, sample_id):
        return next((s for s in self.ms.samples if s.id == sample_id), None)

    def list_samples(self, project_id=None):
        if project_id:
            return [s for s in self.ms.samples if s.project_id == project_id]
        return list(self.ms.samples)

    def create_sample(self, sample):
        self.ms.samples.append(sample)
        return sample

    def resolve_sample(self, sample_id):
        s = next((x for x in self.ms.samples if x.id == sample_id), None)
        if not s:
            s = next((x for x in self.ms.samples if x.sample_id == sample_id), None)
        return s

    def get_run(self, run_id):
        return next((r for r in self.ms.runs if r.id == run_id), None)

    def list_runs(self, project_id=None):
        if project_id:
            return [r for r in self.ms.runs if r.project_id == project_id]
        return list(self.ms.runs)

    def create_run(self, run):
        self.ms.runs.append(run)
        return run

    def get_step(self, step_id):
        return next((s for s in self.ms.run_steps if s.id == step_id), None)

    def list_steps(self, run_id):
        return [s for s in self.ms.run_steps if s.run_id == run_id]

    def create_step(self, step):
        self.ms.run_steps.append(step)
        return step

    def update_step(self, step_id, **kwargs):
        step = self.get_step(step_id)
        if step:
            for k, v in kwargs.items():
                setattr(step, k, v)
        return step

    def list_events(self, run_id):
        return [e for e in self.ms.run_events if e.run_id == run_id]

    def create_event(self, event):
        self.ms.run_events.append(event)
        return event

    def list_logs(self, run_id):
        return [l for l in self.ms.run_logs if l.run_id == run_id]

    def create_log(self, log):
        self.ms.run_logs.append(log)
        return log

    def list_variants(self, sample_id=None, run_id=None):
        items = list(self.ms.variants)
        if sample_id:
            items = [v for v in items if v.sample_id == sample_id]
        if run_id:
            items = [v for v in items if v.run_id == run_id]
        return items

    def create_variant(self, variant):
        self.ms.variants.append(variant)
        return variant

    def get_variant(self, variant_id):
        return next((v for v in self.ms.variants if v.id == variant_id), None)

    def delete_variants_for_run(self, run_id):
        self.ms.variants[:] = [v for v in self.ms.variants if v.run_id != run_id]

    def list_alignment_metrics(self, run_id=None):
        items = list(self.ms.alignment_metrics)
        if run_id:
            items = [a for a in items if a.run_id == run_id]
        return items

    def create_alignment_metrics(self, metrics):
        self.ms.alignment_metrics.append(metrics)
        return metrics

    def list_coverage_metrics(self, run_id=None):
        items = list(self.ms.coverage_metrics)
        if run_id:
            items = [c for c in items if c.run_id == run_id]
        return items

    def create_coverage_metrics(self, metrics):
        self.ms.coverage_metrics.append(metrics)
        return metrics

    def list_structural_variants(self, sample_id=None):
        items = list(self.ms.structural_variants)
        if sample_id:
            items = [s for s in items if s.sample_id == sample_id]
        return items

    def create_structural_variant(self, sv):
        self.ms.structural_variants.append(sv)
        return sv

    def list_cnv_segments(self, sample_id=None):
        items = list(self.ms.cnv_segments)
        if sample_id:
            items = [c for c in items if c.sample_id == sample_id]
        return items

    def create_cnv_segment(self, cnv):
        self.ms.cnv_segments.append(cnv)
        return cnv

    def list_taxonomy_hits(self, sample_id=None):
        items = list(self.ms.taxonomy_hits)
        if sample_id:
            items = [t for t in items if t.sample_id == sample_id]
        return items

    def create_taxonomy_hit(self, hit):
        self.ms.taxonomy_hits.append(hit)
        return hit

    def list_reports(self, run_id=None):
        items = list(self.ms.report_artifacts)
        if run_id:
            items = [r for r in items if r.run_id == run_id]
        return items

    def create_report(self, report):
        self.ms.report_artifacts.append(report)
        return report

    def list_references(self):
        return list(self.ms.references)

    def get_reference(self, ref_id):
        return next((r for r in self.ms.references if r.id == ref_id), None)
