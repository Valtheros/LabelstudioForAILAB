import React from "react";
import { useHistory } from "react-router";
import { ToggleItems } from "../../components";
import { Button } from "@humansignal/ui";
import { Modal } from "../../components/Modal/Modal";
import { Space } from "../../components/Space/Space";
import { useAPI } from "../../providers/ApiProvider";
import { cn } from "../../utils/bem";
import { ConfigPage } from "./Config/Config";
import "./CreateProject.scss";
import { ImportPage } from "./Import/Import";
import { useImportPage } from "./Import/useImportPage";
import { useDraftProject } from "./utils/useDraftProject";
import { Input, TextArea } from "../../components/Form";

const ProjectName = ({ name, setName, onSaveName, onSubmit, error, description, setDescription, show = true }) =>
  !show ? null : (
    <form
      className={cn("project-name").toClassName()}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="w-full flex flex-col gap-2">
        <label className="w-full" htmlFor="project_name">
          Project Name
        </label>
        <Input
          name="name"
          id="project_name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={onSaveName}
          className="project-title w-full"
        />
        {error && <span className="-mt-1 text-negative-content">{error}</span>}
      </div>
      <div className="w-full flex flex-col gap-2">
        <label className="w-full" htmlFor="project_description">
          Description
        </label>
        <TextArea
          name="description"
          id="project_description"
          placeholder="Optional description of your project"
          rows="4"
          style={{ minHeight: 100 }}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="project-description w-full"
        />
      </div>
    </form>
  );

export const CreateProject = ({ onClose }) => {
  const [step, _setStep] = React.useState("name"); // name | import | config
  const [waiting, setWaitingStatus] = React.useState(false);

  const { project, setProject: updateProject, error: draftError, retry: retryDraft } = useDraftProject();
  const history = useHistory();
  const api = useAPI();

  const [name, setName] = React.useState("");
  const [error, setError] = React.useState();
  const [description, setDescription] = React.useState("");
  const [actionError, setActionError] = React.useState("");

  const setStep = React.useCallback((step) => {
    _setStep(step);
    const eventNameMap = {
      name: "project_name",
      import: "data_import",
      config: "labeling_setup",
    };
    __lsa(`create_project.tab.${eventNameMap[step]}`);
  }, []);

  React.useEffect(() => {
    setError(null);
  }, [name]);

  const { columns, uploading, pageProps } = useImportPage();

  const rootClass = cn("create-project");
  const tabClass = rootClass.elem("tab");
  const steps = {
    name: <span className={tabClass.mod({ disabled: !!error }).toClassName()}>Project Name</span>,
    import: <span className={tabClass.toClassName()}>Data Import</span>,
    config: "Labeling Setup",
  };

  // name intentionally skipped from deps:
  // this should trigger only once when we got project loaded
  React.useEffect(() => {
    project && !name && setName(project.title);
  }, [project]);

  const projectBody = React.useMemo(
    () => ({
      title: name,
      description,
      label_config: project?.label_config ?? "<View></View>",
    }),
    [name, description, project?.label_config],
  );

  const onCreate = React.useCallback(async () => {
    if (uploading || waiting || !project?.id || error || !name.trim()) return;
    // First, persist project with label_config so import/reimport validates against it
    setWaitingStatus(true);
    setActionError("");
    try {
      const response = await api.callApi("updateProject", {
        errorFilter: () => true,
        params: { pk: project.id },
        body: { ...projectBody, is_draft: false },
      });
      if (!response?.id) {
        setActionError("Could not save the project. Your changes are still here. Please retry.");
        return;
      }
      __lsa("create_project.create");
      history.push(`/projects/${response.id}/data`);
    } catch {
      setActionError("Could not save the project. Your changes are still here. Please retry.");
    } finally {
      setWaitingStatus(false);
    }
  }, [api, history, project, projectBody, uploading, waiting, error, name]);

  const onSaveName = async () => {
    if (error || !project?.id) return;
    try {
      const res = await api.callApi("updateProjectRaw", {
        params: { pk: project.id },
        body: { title: name },
      });
      if (res?.ok) return;
      const err = await res?.json();
      setError(err?.validation_errors?.title || "Could not save the name. Edit it to retry.");
    } catch {
      setError("Could not save the name. Edit it to retry.");
    }
  };

  const onDelete = React.useCallback(() => {
    if (uploading || waiting) return;
    const performClose = async () => {
      setWaitingStatus(true);
      setActionError("");
      try {
        if (project?.id) {
          const response = await api.callApi("deleteProject", {
            params: { pk: project.id },
            errorFilter: () => true,
          });
          if (!response?.$meta?.ok) {
            setActionError("Could not cancel project creation. Please retry.");
            return;
          }
        }
        updateProject(null);
        onClose?.();
      } catch {
        setActionError("Could not cancel project creation. Please retry.");
      } finally {
        setWaitingStatus(false);
      }
    };
    performClose();
  }, [api, onClose, project, updateProject, uploading, waiting]);

  if (!project?.id) return <Modal onHide={onClose} allowClose={Boolean(draftError)} closeOnClickOutside={false} visible>
    {draftError ? <><p role="alert">{draftError}</p><Space><Button onClick={retryDraft}>Retry</Button><Button look="outlined" onClick={onClose}>Cancel</Button></Space></> : <p role="status">Preparing project...</p>}
  </Modal>;

  return (
    <Modal onHide={onDelete} closeOnClickOutside={false} allowToInterceptEscape fullscreen visible bare>
      <div className={rootClass}>
        <Modal.Header>
          <h1>Create Project</h1>
          <ToggleItems items={steps} active={step} onSelect={setStep} />

          <Space>
            <Button
              variant="negative"
              look="outlined"
              onClick={onDelete}
              waiting={waiting}
              disabled={uploading || waiting}
              aria-label="Cancel project creation"
            >
              Cancel
            </Button>
            <Button
              look="primary"
              onClick={onCreate}
              waiting={waiting || uploading}
              waitingClickable={false}
              disabled={!project || uploading || waiting || error || !name.trim()}
            >
              Save
            </Button>
          </Space>
        </Modal.Header>
        {actionError && <p role="alert" className="px-6 text-negative-content">{actionError}</p>}
        <ProjectName
          name={name}
          setName={setName}
          error={error}
          onSaveName={onSaveName}
          onSubmit={onCreate}
          description={description}
          setDescription={setDescription}
          show={step === "name"}
        />
        <ImportPage
          project={project}
          show={step === "import"}
          {...pageProps}
        />
        <ConfigPage
          project={project}
          onUpdate={(config) => {
            updateProject({ ...project, label_config: config });
          }}
          show={step === "config"}
          columns={columns}
          disableSaveButton={true}
        />
      </div>
    </Modal>
  );
};
