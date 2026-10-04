import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CreationEvidence } from '@/components/creation/creation-evidence';
import { CreationMaterialList } from '@/components/creation/creation-material-list';
import { CreationStructuredEditor } from '@/components/creation/creation-structured-editor';
import { CreationTaskStatus } from '@/components/creation/creation-task-status';
import { CreationVersionEditor } from '@/components/creation/creation-version-editor';
import {
  creationMaterial,
  creationRevision,
  creationTask,
} from '../helpers/creation-fixtures';
import { mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

describe('creation human decisions and uncertain outcomes', () => {
  it('saves the chosen pinned image on its exact page and excludes other images', async () => {
    mockHttpResponses([creationRevision]);
    const image: API.CreationMaterialResponse = {
      ...creationMaterial,
      id: 'owned-image',
      kind: 'image',
      title: '授权原图.webp',
      current_revision: {
        ...creationMaterial.current_revision,
        id: 'image-revision',
      },
    };
    const outside = {
      ...image,
      id: 'outside-image',
      title: '未选入任务的图片.webp',
      current_revision: { ...image.current_revision, id: 'outside-revision' },
    };
    const pending = {
      ...image,
      id: 'pending-image',
      title: '待确认图片.webp',
      current_revision: {
        ...image.current_revision,
        id: 'pending-revision',
        confirmed: false,
      },
    };
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <CreationVersionEditor
        task={{
          ...creationTask,
          material_revision_ids: [
            'material-revision-1',
            'image-revision',
            'pending-revision',
          ],
        }}
        materials={[creationMaterial, image, outside, pending]}
        formats={[]}
        busy={false}
        onSave={save}
        onConfirm={vi.fn()}
        onDirtyChange={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole('combobox', { name: '授权配图 · 第 1 项' }),
    );
    expect(
      screen.queryByRole('option', { name: outside.title }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: pending.title }),
    ).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('option', { name: image.title }));
    expect(
      screen.getByRole('button', { name: '核对后确认采用' }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '保存人工新版本' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledExactlyOnceWith({
        expected_revision_id: creationRevision.id,
        text: creationRevision.text,
        data: {
          ...creationRevision.data,
          pages: [
            {
              id: 'page-1',
              title: '标题',
              body: '卡片正文',
              image_material_id: 'owned-image',
            },
          ],
        },
      }),
    );
  });

  it('cannot select unconfirmed materials as a task input', () => {
    const material = {
      ...creationMaterial,
      current_revision: {
        ...creationMaterial.current_revision,
        confirmed: false,
      },
    };
    const confirm = vi.fn().mockResolvedValue(undefined);
    render(
      <CreationMaterialList
        materials={[material]}
        selected={[]}
        onSelect={vi.fn()}
        busy={false}
        onSave={vi.fn()}
        onConfirm={confirm}
      />,
    );
    expect(screen.getByRole('checkbox', { name: '原创材料' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '核对后确认材料' }));
    expect(confirm).toHaveBeenCalledWith(material);
  });

  it('requires explicit renewed authorization before retrying an unknown paid operation', () => {
    const retry = vi.fn().mockResolvedValue(undefined);
    render(
      <CreationTaskStatus
        task={{
          ...creationTask,
          status: 'outcome_unknown',
          usage: {
            ...creationTask.usage,
            calls_reserved: 1,
            unknown_operations: 1,
          },
        }}
        busy={false}
        onCancel={vi.fn()}
        onRetry={retry}
      />,
    );
    expect(retry).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: '明确开始一次新尝试' }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /我已核对旧调用/ }));
    fireEvent.click(screen.getByRole('button', { name: '明确开始一次新尝试' }));
    expect(retry).toHaveBeenCalledExactlyOnceWith(true);
    expect(screen.getByText(/保留预算占用/)).toBeInTheDocument();
  });

  it('saves against the loaded revision and preserves structured metadata without a new model task', async () => {
    mockHttpResponses([creationRevision]);
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <CreationVersionEditor
        task={creationTask}
        materials={[creationMaterial]}
        formats={[]}
        busy={false}
        onSave={save}
        onConfirm={vi.fn()}
        onDirtyChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('可编辑母稿'), {
      target: { value: '作者确认的新稿。' },
    });
    expect(
      screen.getByRole('button', { name: '核对后确认采用' }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '保存人工新版本' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledExactlyOnceWith({
        expected_revision_id: 'revision-1',
        text: '作者确认的新稿。',
        data: creationRevision.data,
      }),
    );
  });

  it('keeps unsaved work when a concurrent remote revision arrives', async () => {
    mockHttpResponses([creationRevision], [creationRevision]);
    const props = {
      materials: [creationMaterial],
      formats: [],
      busy: false,
      onSave: vi.fn(),
      onConfirm: vi.fn(),
      onDirtyChange: vi.fn(),
    };
    const view = render(
      <CreationVersionEditor task={creationTask} {...props} />,
    );
    fireEvent.change(screen.getByLabelText('可编辑母稿'), {
      target: { value: '仍未保存的人工修改。' },
    });
    view.rerender(
      <CreationVersionEditor
        task={{
          ...creationTask,
          revision: {
            ...creationRevision,
            id: 'revision-2',
            number: 2,
            text: '来自另一端的已保存新稿。',
          },
        }}
        {...props}
      />,
    );
    expect(screen.getByLabelText('可编辑母稿')).toHaveValue(
      '仍未保存的人工修改。',
    );
    expect(screen.getByText('服务器已有更新版本')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '保存人工新版本' }),
    ).toBeDisabled();
  });

  it('binds a new mother manuscript to an exact confirmed revision and blocks unsaved edits', () => {
    mockHttpResponses([creationRevision]);
    const useAsMaterial = vi.fn().mockResolvedValue(undefined);
    render(
      <CreationVersionEditor
        task={{
          ...creationTask,
          revision: { ...creationRevision, confirmed: true },
        }}
        materials={[creationMaterial]}
        formats={[]}
        busy={false}
        onSave={vi.fn()}
        onConfirm={vi.fn()}
        onDirtyChange={vi.fn()}
        onUseAsMaterial={useAsMaterial}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '用确认结果作母稿' }));
    expect(useAsMaterial).toHaveBeenCalledExactlyOnceWith('revision-1');
    fireEvent.change(screen.getByLabelText('可编辑母稿'), {
      target: { value: '尚未保存的改稿。' },
    });
    expect(
      screen.getByRole('button', { name: '用确认结果作母稿' }),
    ).toBeDisabled();
  });

  it('changes card order while preserving the original source and opaque metadata', () => {
    const change = vi.fn();
    const data = {
      pages: [
        { id: 'a', title: '第一', body: '内容甲' },
        { id: 'b', title: '第二', body: '内容乙' },
      ],
      source_metadata: { source: 'original' },
    };
    render(
      <CreationStructuredEditor
        data={data}
        onChange={change}
        disabled={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '将第 2 项上移' }));
    expect(change).toHaveBeenCalledExactlyOnceWith({
      ...data,
      pages: [data.pages[1], data.pages[0]],
    });
    expect(data.pages[0].id).toBe('a');
  });

  it('does not substitute the current material text for an old evidence hash', () => {
    render(
      <CreationEvidence
        materials={[creationMaterial]}
        data={{
          evidence: [
            {
              material_id: creationMaterial.id,
              sha256: 'c'.repeat(64),
              start: 0,
              end: 2,
              quote: '旧稿',
            },
          ],
        }}
      />,
    );
    expect(
      screen.queryByText('明确观察到的数据只有十次。'),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/当前原文不能替代其来源/)).toBeInTheDocument();
  });
});
