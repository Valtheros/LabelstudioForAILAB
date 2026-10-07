import { useEffect, useState } from 'react';
import { Button } from '@humansignal/ui';
import { useAPI } from '../../providers/ApiProvider';
import { absoluteURL } from '../../utils/helpers';

export function ImportStatus({ projectId }) {
  const api = useAPI();
  const [operation, setOperation] = useState(null);
  const [error, setError] = useState('');
  const [updating, setUpdating] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    let timer;
    const check = async () => {
      if (!document.hidden) {
        const data = await api.callApi('ailabOperations', { params: { pk: projectId }, signal: controller.signal, errorFilter: () => true });
        if (controller.signal.aborted) return;
        if (!data || data.error) setError('Import status unavailable. Your saved work is unchanged. Retrying.');
        else {
          setError('');
          setOperation(data.operations?.find((op) => op.kind === 'import') ?? null);
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(check, 5000);
    };
    void check();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [api, projectId, refresh]);
  if (!operation && !error) return null;
  const active = operation && ['queued', 'running'].includes(operation.status);
  const update = async () => {
    setUpdating(true);
    const data = await api.callApi('ailabOperationAction', { params: { pk: projectId, id: operation.id, action: active ? 'cancel' : 'retry' }, errorFilter: () => true });
    setUpdating(false);
    if (data?.error) setError(data.response?.detail || 'Could not update import. Retry.');
    else setRefresh((r) => r + 1);
  };
  const text = !operation ? '' : active ? `Import ${operation.status}: ${operation.processed} / ${operation.total}`
    : operation.status === 'completed' ? `Imported ${operation.result?.imported ?? 0} images. ${operation.result?.duplicates ?? 0} duplicates, ${operation.result?.skipped ?? 0} skipped.`
    : operation.status === 'failed' ? `Import failed: ${operation.error}` : 'Import cancelled';
  return <div className="flex flex-wrap items-center gap-3 border-b px-5 py-3 text-sm" aria-label="Image import status">
    <span role="status" className="min-w-0 break-words">{error || text}</span>
    {operation && (active || ['failed', 'cancelled'].includes(operation.status)) &&
      <Button size="small" look="outlined" disabled={updating} onClick={update}>{active ? 'Cancel import' : 'Retry import'}</Button>}
    {operation?.status === 'completed' && <a href={absoluteURL(`/projects/${projectId}/data`)} data-external>View images</a>}
  </div>;
}
